"""Source-only Authority transport tests; all signer material is ephemeral pytest state."""
import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from licensing.authority import LicenseAuthority, activation_challenge
from licensing.authority_api import (
    HealthDescriptor, OwnerAuthorization, PeerDescriptor, ServiceIdentity,
    create_authority_app,
)
from licensing.signer_ceremony import DOMAIN, PURPOSE, OfflineFixtureMonotonicAnchor

NOW = datetime(2026, 8, 8, 5, 0, tzinfo=timezone.utc)


class Signer:
    def __init__(self, key): self.key = key
    def sign(self, value): return self.key.sign(value)


class Descriptor:
    def __init__(self, authority, **changes): self.authority, self.changes = authority, changes
    def descriptor(self): return self.authority.handshake() | {"status": "active"} | self.changes


class Anchor:
    def __init__(self, good=True, explode=False): self.good, self.explode = good, explode
    def verify(self, descriptor):
        if self.explode: raise RuntimeError("SECRET_ANCHOR")
        return self.good


class Replay:
    def __init__(self): self.values = set(); self.calls = 0
    def consume(self, subject, nonce, timestamp):
        self.calls += 1; value = (subject, nonce, timestamp)
        if value in self.values: return False
        self.values.add(value); return True


class ServiceVerifier:
    def __init__(self, authority, *, mutate=None, explode=False):
        self.authority, self.mutate, self.explode, self.calls = authority, mutate, explode, []
    def verify(self, request):
        self.calls.append(request)
        if self.explode: raise RuntimeError("SECRET_SERVICE_TOKEN")
        expected = hashlib.sha256((request.method + "\0" + request.path + "\0" + request.body_sha256 + "\0" + request.timestamp + "\0" + request.nonce + "\0" + request.audience + "\0" + request.authority_id).encode()).hexdigest().encode()
        if request.credential != expected: return None
        identity = ServiceIdentity("payments", request.audience, request.authority_id)
        return self.mutate(identity) if self.mutate else identity


class OwnerVerifier:
    def __init__(self, allow=True, explode=False): self.allow, self.explode, self.calls = allow, explode, 0
    def authorize(self, **value):
        self.calls += 1
        if self.explode: raise RuntimeError("SECRET_OWNER")
        if not self.allow or value["credential"] != b"Owner proof": return None
        return OwnerAuthorization("buyer", "owner", value["license_id"], value["device_id"])


@pytest.fixture
def authority(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    ceremony = {"schema_version": 1, "purpose": PURPOSE, "domain": DOMAIN, "algorithm": "Ed25519",
        "authority_id": "authority-test", "key_id": "fixture-key", "generation": 1,
        "activated_at": "2026-08-01T00:00:00Z", "predecessor_generation": None,
        "public_key_sha256": hashlib.sha256(public).hexdigest(), "provider_attestation_id": "fixture:ephemeral"}
    return LicenseAuthority.from_external_signer(tmp_path / "authority.sqlite", signer=Signer(key),
        ceremony_descriptor=ceremony, reviewed_public_key=public,
        generation_anchor=OfflineFixtureMonotonicAnchor(), now=lambda: NOW)


class ProductionJournal:
    production_safe = True; fixture = False; process_local = False
    def execute(self, _assertion, _identity, operation): return operation()


def production_provider(value):
    value.production_safe = True; value.fixture = False; value.process_local = False
    return value


def production_app(authority, **changes):
    values = dict(authority=authority, service_verifier=production_provider(ServiceVerifier(authority)),
        request_journal=ProductionJournal(), owner_verifier=production_provider(OwnerVerifier()),
        signer_descriptor_provider=production_provider(Descriptor(authority)),
        anchor_verifier=production_provider(Anchor()), peer_resolver=lambda request: PeerDescriptor("payments-fixture"),
        now=lambda: NOW, production=True)
    values.update(changes)
    return create_authority_app(**values)


def app(authority, **changes):
    values = dict(authority=authority, service_verifier=ServiceVerifier(authority), replay_store=Replay(),
        owner_verifier=OwnerVerifier(), signer_descriptor_provider=Descriptor(authority), anchor_verifier=Anchor(),
        peer_resolver=lambda request: PeerDescriptor("payments-fixture"), now=lambda: NOW)
    values.update(changes)
    return create_authority_app(**values)


def service_headers(authority, path, raw, **changes):
    timestamp = NOW.isoformat().replace("+00:00", "Z"); nonce = changes.pop("nonce", "abcdefghijklmnop")
    audience = changes.pop("audience", "growthmap-authority"); authority_id = changes.pop("authority_id", authority.authority_id)
    digest = changes.pop("digest", hashlib.sha256(raw).hexdigest())
    proof = hashlib.sha256(("POST\0" + path + "\0" + digest + "\0" + timestamp + "\0" + nonce + "\0" + audience + "\0" + authority_id).encode()).hexdigest()
    result = {"X-Authority-Service-Auth": proof, "X-Authority-Timestamp": timestamp,
        "X-Authority-Nonce": nonce, "X-Authority-Audience": audience, "X-Authority-Id": authority_id,
        "Content-Type": "application/json"}
    result.update(changes); return result


def entitlement(authority):
    return {"source": "payments", "source_id": "1" * 64, "payload_digest": "2" * 64,
        "authority_id": authority.authority_id, "signer_identity": authority.handshake(),
        "edition": "personal", "major_version": 1, "seat_limit": 2}


def read_request(authority):
    return {"source": "payments", "source_id": "1" * 64, "authority_id": authority.authority_id,
        "signer_identity": authority.handshake()}


def revocation_request(authority, license_id, created_at):
    return {"source": "payments", "source_id": "1" * 64, "payload_digest": "2" * 64,
        "authority_id": authority.authority_id, "signer_identity": authority.handshake(),
        "license_id": license_id, "action": "revoke", "reason": "administrative",
        "payment_proof": "3" * 64, "tx_hash": "0x" + "4" * 64, "created_at": created_at}


def post_service(client, authority, path, value, **headers):
    raw = json.dumps(value, separators=(",", ":")).encode()
    return client.post(path, content=raw, headers=service_headers(authority, path, raw, **headers))


def direct_asgi(application, *, path="/v1/authority/identity", method="GET", headers=None, body=b"",
                request_messages=None):
    """Invoke ASGI directly so raw headers and receive-frame sequences remain observable."""
    messages = []
    supplied = list(headers or [])
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "headers": supplied,
        "client": ("127.0.0.1", 1234), "server": ("authority.test", 443)}
    receive_frames = list(request_messages) if request_messages is not None else [
        {"type": "http.request", "body": body, "more_body": False}]
    async def receive():
        if receive_frames: return receive_frames.pop(0)
        return {"type": "http.disconnect"}
    async def send(message): messages.append(message)
    asyncio.run(application(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    payload = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), payload


def assert_generic(response, status):
    assert response.status_code == status
    assert response.json()["detail"] in {"request denied", "invalid request", "resource unavailable", "service unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "SECRET" not in response.text


def test_production_and_missing_provider_fail_closed(authority):
    with pytest.raises(RuntimeError, match="dependencies unavailable"):
        create_authority_app(authority=authority, production=True)
    assert_generic(TestClient(create_authority_app(authority=authority)).get("/v1/authority/identity"), 503)
    value = entitlement(authority); raw = json.dumps(value).encode()
    client = TestClient(create_authority_app(authority=authority, signer_descriptor_provider=Descriptor(authority), anchor_verifier=Anchor()))
    before = authority._connect().execute("select count(*) from external_entitlements").fetchone()[0]
    assert_generic(client.post("/v1/service/entitlements", content=raw, headers=service_headers(authority, "/v1/service/entitlements", raw)), 503)
    with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0] == before


@pytest.mark.parametrize("change", [
    {"audience": "wrong-audience"}, {"authority_id": "wrong-authority"}, {"digest": "0" * 64},
    {"nonce": "short"}, {"X-Authority-Timestamp": "2000-01-01T00:00:00Z"},
    {"X-Authority-Service-Auth": "wrong"},
])
def test_service_binding_negative_matrix_has_zero_side_effect(authority, change):
    client = TestClient(app(authority)); value = entitlement(authority)
    result = post_service(client, authority, "/v1/service/entitlements", value, **change)
    assert_generic(result, 403)
    with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0


def test_service_replay_and_response_loss_restart_are_idempotent(authority):
    value = entitlement(authority); first_client = TestClient(app(authority))
    first = post_service(first_client, authority, "/v1/service/entitlements", value)
    assert first.status_code == 200
    replay = post_service(first_client, authority, "/v1/service/entitlements", value)
    assert_generic(replay, 403)
    # A restarted transport has a durable external replay store in production. This explicit
    # fresh fixture represents response loss after Authority commit and returns the same ack.
    second = post_service(TestClient(app(authority)), authority, "/v1/service/entitlements", value, nonce="qrstuvwxyzABCDEF")
    assert second.status_code == 200 and second.content == first.content
    with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 1


@pytest.mark.parametrize("path,kind", [
    ("/v1/service/entitlements", "entitlement"),
    ("/v1/service/entitlements/read", "read"),
    ("/v1/service/revocations", "revocation"),
    ("/v1/service/revocations/read", "read"),
])
def test_body_signer_identity_mismatch_precedes_verifier_replay_and_side_effect(authority, path, kind):
    replay = Replay(); verifier = ServiceVerifier(authority); client = TestClient(app(authority, replay_store=replay, service_verifier=verifier))
    value = entitlement(authority)
    if kind == "read": value = {k: value[k] for k in ("source", "source_id", "authority_id", "signer_identity")}
    elif kind == "revocation": value = {k: value[k] for k in ("source", "source_id", "payload_digest", "authority_id", "signer_identity")} | {"license_id": "gm_" + "a" * 32, "action": "revoke", "reason": "administrative", "payment_proof": "3" * 64, "tx_hash": "0x" + "4" * 64, "created_at": "2026-08-08T05:00:00Z"}
    value["signer_identity"] = value["signer_identity"] | {"key_id": "wrong-key"}
    first = post_service(client, authority, path, value)
    second = post_service(client, authority, path, value)  # same nonce remains unconsumed
    assert_generic(first, 403); assert_generic(second, 403)
    assert replay.calls == 0 and verifier.calls == []
    with authority._connect() as db:
        assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0
        assert db.execute("select count(*) from external_revocations").fetchone()[0] == 0


def test_body_authority_id_mismatch_does_not_burn_nonce(authority):
    replay = Replay(); verifier = ServiceVerifier(authority); client = TestClient(app(authority, replay_store=replay, service_verifier=verifier))
    value = entitlement(authority) | {"authority_id": "wrong-authority"}
    assert_generic(post_service(client, authority, "/v1/service/entitlements", value), 403)
    assert replay.calls == 0 and verifier.calls == []


def test_verifier_identity_mismatch_and_peer_seam(authority):
    verifier = ServiceVerifier(authority, mutate=lambda value: ServiceIdentity(value.subject, "wrong", value.authority_id))
    client = TestClient(app(authority, service_verifier=verifier)); value = entitlement(authority)
    assert_generic(post_service(client, authority, "/v1/service/entitlements", value), 403)
    assert verifier.calls and verifier.calls[0].peer == PeerDescriptor("payments-fixture")
    with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0


@pytest.mark.parametrize("provider", [None, Descriptor])
def test_descriptor_absent_or_pin_generation_mismatch_is_not_ready(authority, provider):
    descriptor = None if provider is None else provider(authority, generation=2)
    client = TestClient(app(authority, signer_descriptor_provider=descriptor))
    assert_generic(client.get("/v1/authority/identity"), 503)


@pytest.mark.parametrize("anchor", [Anchor(False), Anchor(explode=True)])
def test_stale_or_missing_anchor_is_not_ready(authority, anchor):
    client = TestClient(app(authority, anchor_verifier=anchor))
    assert_generic(client.get("/v1/authority/identity"), 503)


def test_identity_is_minimal_and_public_key_private_material_never_exposed(authority):
    # Regression: real TestClient supplies its normal GET headers (including version-dependent
    # body framing choices); a bodyless identity request must not be treated as mutation JSON.
    response = TestClient(app(authority)).get("/v1/authority/identity")
    assert response.status_code == 200
    assert set(response.json()) == set(HealthDescriptor.model_fields)
    text = response.text.lower()
    assert "private" not in text and "pem" not in text and "attestation" not in text and "fixture:ephemeral" not in text


def test_json_confusables_constants_depth_nodes_strings_and_integer_abuse(authority):
    client = TestClient(app(authority)); endpoint = "/v1/licenses/activation/challenge"
    attacks = [
        '{"license_id":"a","licens\\u0065_id":"b","device_public_key":"' + "A" * 44 + '"}',
        '{"license_id":"a","licens\\u0065_\\u0069d":"b","device_public_key":"' + "A" * 44 + '"}',
        '{"license_id":NaN,"device_public_key":"' + "A" * 44 + '"}',
        '{"license_id":Infinity,"device_public_key":"' + "A" * 44 + '"}',
        '{"license_id":-Infinity,"device_public_key":"' + "A" * 44 + '"}',
        json.dumps({"license_id": "a", "device_public_key": "A" * 4097}),
        json.dumps({"license_id": 2**80, "device_public_key": "A" * 44}),
        json.dumps({"license_id": [[[[[[[[["a"]]]]]]]]], "device_public_key": "A" * 44}),
        json.dumps({"license_id": [0] * 33, "device_public_key": "A" * 44}),
    ]
    # decomposed Unicode key normalizes to an existing-looking form and is rejected before Pydantic
    attacks.append(json.dumps({"licens\u0065_id": "a", "de\u0301vice_public_key": "A" * 44}, ensure_ascii=False))
    for payload in attacks:
        assert_generic(client.post(endpoint, content=payload.encode(), headers={"content-type": "application/json"}), 400)


def test_bodyless_get_and_head_framing_policy(authority):
    application = app(authority, expose_schema_for_tests=True)
    for path, headers, body, expected in [
        ("/v1/authority/identity", [], b"", 200),
        ("/v1/authority/identity", [(b"content-length", b"0")], b"", 200),
        ("/not-found", [(b"content-length", b"0")], b"", 404),
        ("/docs", [(b"content-length", b"0")], b"", 200),
        ("/v1/authority/identity", [(b"content-length", b"1")], b"x", 400),
        ("/v1/authority/identity", [(b"content-length", b"1")], b"", 400),
        ("/v1/authority/identity", [(b"transfer-encoding", b"chunked")], b"", 400),
    ]:
        status, response_headers, payload = direct_asgi(application, path=path, headers=headers, body=body)
        assert status == expected and response_headers[b"cache-control"] == b"no-store"
        if expected in {400, 404}: assert b'"detail"' in payload
    # HEAD is not exposed by this candidate and remains a generic 405, not a false framing 400.
    status, response_headers, _ = direct_asgi(application, method="HEAD", headers=[(b"content-length", b"0")])
    assert status == 405 and response_headers[b"cache-control"] == b"no-store"


def test_framework_errors_docs_queries_and_clock_are_generic(authority):
    client = TestClient(app(authority))
    for response, status in [
        (client.get("/not-found"), 404),
        (client.get("/v1/licenses/activation/challenge"), 405),
        (client.post("/v1/licenses/activation/challenge?x=1", json={}), 400),
        (client.get("/docs"), 404), (client.get("/openapi.json"), 404), (client.get("/redoc"), 404),
    ]: assert_generic(response, status)
    with pytest.raises(RuntimeError, match="clock unavailable"):
        create_authority_app(authority=authority, now=lambda: datetime(2026, 8, 8))


@pytest.mark.parametrize("bad_name", [
    b"bad:name", b"bad name", b"bad(name)", b"bad/name", b"bad=name", b"bad?name",
    b"bad@name", b"bad[name]", b"bad{name}", b'bad\"name', b"bad\\name", b"bad\x00name",
    b"bad\x7fname", b"bad\x80name",
])
def test_direct_asgi_rejects_non_token_header_names(authority, bad_name):
    status, headers, body = direct_asgi(app(authority), headers=[(bad_name, b"value")])
    assert status == 400 and headers[b"cache-control"] == b"no-store" and b"invalid request" in body


@pytest.mark.parametrize("bad_value", [b"a\r\nb", b"a\x00b", b"a\x01b", b"a\tb", b"a\x1fb", b"a\x7fb", b"a\x80b"])
def test_direct_asgi_rejects_ctl_and_non_ascii_header_values(authority, bad_value):
    status, _, _ = direct_asgi(app(authority), headers=[(b"x-test", bad_value)])
    assert status == 400


@pytest.mark.parametrize("byte", b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
def test_direct_asgi_accepts_every_tchar_and_normal_values(authority, byte):
    status, _, _ = direct_asgi(app(authority), headers=[(b"x" + bytes([byte]), b"normal ASCII value")])
    assert status == 200


@pytest.mark.parametrize("extra", [
    [(b"content-length", b"x")], [(b"content-length", b"+2")],
    [(b"content-length", b" 2")], [(b"content-length", b"02")],
    [(b"content-length", b"2,2")], [(b"content-length", b"999999999999999999999")],
    [(b"content-length", b"2"), (b"content-length", b"2")],
    [(b"transfer-encoding", b"chunked")],
    [(b"content-length", b"2"), (b"transfer-encoding", b"chunked")],
])
def test_direct_asgi_rejects_invalid_length_duplicates_and_transfer_encoding(authority, extra):
    status, _, _ = direct_asgi(app(authority), path="/v1/licenses/activation/challenge", method="POST",
        headers=[(b"content-type", b"application/json"), *extra], body=b"{}")
    assert status == 400


def _service_asgi(authority, raw, frames, *, declared=True):
    verifier = ServiceVerifier(authority); replay = Replay()
    headers = [(b"content-type", b"application/json")]
    if declared: headers.append((b"content-length", str(len(raw)).encode()))
    status, response_headers, payload = direct_asgi(
        app(authority, service_verifier=verifier, replay_store=replay),
        path="/v1/service/entitlements", method="POST",
        headers=[*headers, *[(key.encode(), value.encode()) for key, value in
            service_headers(authority, "/v1/service/entitlements", raw).items()
            if key.lower() != "content-type"]], request_messages=frames)
    return status, response_headers, payload, verifier, replay


def _assert_zero_transport_effects(authority, verifier, replay):
    assert verifier.calls == [] and replay.calls == 0
    with authority._connect() as db:
        assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0
        assert db.execute("select count(*) from external_revocations").fetchone()[0] == 0


def test_receive_multiple_nonempty_chunks_exact_length_operates_once(authority):
    raw = json.dumps(entitlement(authority), separators=(",", ":")).encode()
    cut = len(raw) // 2
    status, headers, payload, verifier, replay = _service_asgi(authority, raw, [
        {"type": "http.request", "body": raw[:cut], "more_body": True},
        {"type": "http.request", "body": raw[cut:], "more_body": False},
    ])
    assert status == 200 and headers[b"cache-control"] == b"no-store"
    assert json.loads(payload)["delivery_receipt"]
    assert len(verifier.calls) == 1 and replay.calls == 1
    with authority._connect() as db:
        assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 1


def test_receive_empty_intermediate_and_terminal_chunks_account_exactly(authority):
    raw = json.dumps(entitlement(authority), separators=(",", ":")).encode()
    status, _, payload, verifier, replay = _service_asgi(authority, raw, [
        {"type": "http.request", "body": b"", "more_body": True},
        {"type": "http.request", "body": raw, "more_body": True},
        {"type": "http.request", "body": b"", "more_body": False},
    ])
    assert status == 200 and json.loads(payload)["delivery_receipt"]
    assert len(verifier.calls) == 1 and replay.calls == 1
    with authority._connect() as db:
        assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 1


def test_receive_disconnect_before_terminal_frame_fails_closed(authority):
    raw = json.dumps(entitlement(authority), separators=(",", ":")).encode()
    status, headers, payload, verifier, replay = _service_asgi(authority, raw, [
        {"type": "http.request", "body": raw, "more_body": True},
        {"type": "http.disconnect"},
    ])
    # Starlette currently raises ClientDisconnect; the generic exception boundary owns its
    # version-independent fail-closed mapping rather than exposing that framework type/name.
    assert status == 500 and headers[b"cache-control"] == b"no-store"
    assert b'"detail"' in payload and b"ClientDisconnect" not in payload
    _assert_zero_transport_effects(authority, verifier, replay)


def test_receive_content_length_mismatch_across_chunks_precedes_auth(authority):
    raw = json.dumps(entitlement(authority), separators=(",", ":")).encode()
    for frames in ([
        {"type": "http.request", "body": raw[:-1], "more_body": True},
        {"type": "http.request", "body": b"", "more_body": False},
    ], [
        {"type": "http.request", "body": raw, "more_body": True},
        {"type": "http.request", "body": b"x", "more_body": False},
    ]):
        status, headers, payload, verifier, replay = _service_asgi(authority, raw, frames)
        assert status == 400 and headers[b"cache-control"] == b"no-store" and b'"detail"' in payload
        _assert_zero_transport_effects(authority, verifier, replay)


def test_receive_absent_length_later_chunk_overrun_rejects_zero_effects(authority):
    raw = json.dumps(entitlement(authority), separators=(",", ":")).encode()
    status, headers, payload, verifier, replay = _service_asgi(authority, raw, [
        {"type": "http.request", "body": raw, "more_body": True},
        {"type": "http.request", "body": b"x" * (16_384 - len(raw) + 1), "more_body": True},
        # Must reject on the overrun frame without waiting for a terminal frame.
        {"type": "http.disconnect"},
    ], declared=False)
    assert status == 413 and headers[b"cache-control"] == b"no-store" and b'"detail"' in payload
    _assert_zero_transport_effects(authority, verifier, replay)


@pytest.mark.parametrize("declared,body", [(b"1", b"x" * 122), (b"1", b"{}"), (b"3", b"{}"), (b"0", b"{}"), (b"1", b"")])
def test_content_length_mismatch_precedes_auth_and_side_effect(authority, declared, body):
    verifier = ServiceVerifier(authority); replay = Replay()
    application = app(authority, service_verifier=verifier, replay_store=replay)
    before = authority._connect().execute("select count(*) from external_entitlements").fetchone()[0]
    status, _, _ = direct_asgi(application, path="/v1/service/entitlements", method="POST",
        headers=[(b"content-type", b"application/json"), (b"content-length", declared)], body=body)
    assert status == 400 and verifier.calls == [] and replay.calls == 0
    with authority._connect() as db:
        assert db.execute("select count(*) from external_entitlements").fetchone()[0] == before


@pytest.mark.parametrize("created_at", ["2026-08-08T05:00:00Z", "2026-08-08T05:00:00+00:00",
    "2026-08-08T05:00:00.123456Z", "2026-08-08T05:00:00.123456+00:00"])
def test_revocation_accepts_exact_utc_adapter_forms_without_rewriting(authority, created_at):
    client = TestClient(app(authority))
    issued = post_service(client, authority, "/v1/service/entitlements", entitlement(authority))
    assert issued.status_code == 200
    value = revocation_request(authority, issued.json()["license_id"], created_at)
    response = post_service(client, authority, "/v1/service/revocations", value, nonce="qrstuvwxyzABCDEF")
    assert response.status_code == 200
    with authority._connect() as db:
        assert db.execute("select event_created_at from external_revocations").fetchone()[0] == created_at


@pytest.mark.parametrize("created_at", ["2026-08-08T05:00:00", "2026-08-08T05:00:00+01:00",
    "2026-08-08T05:00:00-00:01", "2026-08-08 05:00:00Z", "2026-08-08T05:00Z",
    "2026-08-08T05:00:00.1234567Z", "2026-08-08T05:00:00z", "2026-02-29T05:00:00Z",
    "2026-13-08T05:00:00Z", "2026-08-08T24:00:00Z", "2016-12-31T23:59:60Z", "malformed"])
def test_revocation_rejects_noncanonical_or_non_utc_timestamps_before_auth(authority, created_at):
    verifier = ServiceVerifier(authority); replay = Replay()
    client = TestClient(app(authority, service_verifier=verifier, replay_store=replay))
    value = revocation_request(authority, "gm_" + "a" * 32, created_at)
    assert_generic(post_service(client, authority, "/v1/service/revocations", value), 400)
    assert verifier.calls == [] and replay.calls == 0


def test_content_length_header_failures_precede_all_security_and_authority_effects(authority):
    cases = [
        ([(b"content-length", b"01")], b"{}", 400),
        ([(b"content-length", b"999999999999999999999")], b"{}", 400),
        ([(b"content-length", b"2"), (b"transfer-encoding", b"chunked")], b"{}", 400),
        ([(b"content-length", b"2"), (b"content-length", b"2")], b"{}", 400),
        ([], b"x" * (16_384 + 1), 413),  # absent CL: ASGI body remains stream-bounded
    ]
    for extra, body, expected in cases:
        verifier = ServiceVerifier(authority); replay = Replay()
        status, _, _ = direct_asgi(app(authority, service_verifier=verifier, replay_store=replay),
            path="/v1/service/entitlements", method="POST",
            headers=[(b"content-type", b"application/json"), *extra], body=body)
        assert status == expected and verifier.calls == [] and replay.calls == 0
        with authority._connect() as db:
            assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0
            assert db.execute("select count(*) from external_revocations").fetchone()[0] == 0


def test_authenticated_create_read_revoke_read_exact_response_models(authority):
    client = TestClient(app(authority))
    created = post_service(client, authority, "/v1/service/entitlements", entitlement(authority))
    assert created.status_code == 200
    assert set(created.json()) == {"license_id", "edition", "major_version", "device_allowance",
        "delivery_receipt", "authority_id", "signer_identity", "ack_signature"}
    readback = post_service(client, authority, "/v1/service/entitlements/read", read_request(authority),
        nonce="entitlementread01")
    assert readback.status_code == 200
    assert set(readback.json()) == {"source", "source_id", "payload_digest", "license_id",
        "authority_id", "signer_identity", "delivery_receipt", "ack_signature"}
    revoked = post_service(client, authority, "/v1/service/revocations",
        revocation_request(authority, created.json()["license_id"], "2026-08-08T05:00:00Z"),
        nonce="revocationwrite1")
    assert revoked.status_code == 200
    assert set(revoked.json()) == {"license_id", "revoked_at", "revocation_receipt",
        "authority_id", "signer_identity", "ack_signature"}
    revocation_read = post_service(client, authority, "/v1/service/revocations/read", read_request(authority),
        nonce="revocationread01")
    assert revocation_read.status_code == 200
    assert set(revocation_read.json()) == {"source", "source_id", "payload_digest", "license_id",
        "action", "reason", "payment_proof", "tx_hash", "created_at", "revoked_at",
        "request_digest", "revocation_receipt", "authority_id", "signer_identity", "ack_signature"}


def test_extra_secret_from_authority_fails_closed_response_validation(authority, monkeypatch):
    original = authority.create_external_entitlement
    def leaking(**kwargs): return original(**kwargs) | {"secret": "SECRET_OUTPUT"}
    monkeypatch.setattr(authority, "create_external_entitlement", leaking)
    response = post_service(TestClient(app(authority), raise_server_exceptions=False), authority,
        "/v1/service/entitlements", entitlement(authority))
    assert_generic(response, 500)
    assert "SECRET_OUTPUT" not in response.text


def test_production_omitted_policy_is_exact_service_only_and_invalid_policy_fails_before_construction(authority, monkeypatch):
    import licensing.authority_api as api
    gift_constructions=[]
    monkeypatch.setattr(api,'GiftLicenseService',lambda *_:gift_constructions.append(1))
    application=production_app(authority)
    expected={"/v1/authority/identity","/v1/service/entitlements","/v1/service/entitlements/read",
        "/v1/service/revocations","/v1/service/revocations/read"}
    assert {route.path for route in application.routes if getattr(route,'path','').startswith('/v1/')}==expected
    assert gift_constructions==[]
    for policy in ('all','ALL','service_only','service-only-alias','',None,False,1,object()):
        gift_constructions.clear()
        with pytest.raises(RuntimeError,match='composition invalid'):
            production_app(authority,route_policy=policy)
        assert gift_constructions==[]


def test_production_excluded_route_alias_matrix_and_identity_are_effect_free(authority, monkeypatch):
    calls=[]
    for name in ('issue_activation_challenge','activate_challenge','deactivate'):
        monkeypatch.setattr(authority,name,lambda *a,_name=name,**k:calls.append(_name))
    application=production_app(authority)
    expected={"/v1/authority/identity","/v1/service/entitlements","/v1/service/entitlements/read",
        "/v1/service/revocations","/v1/service/revocations/read"}
    excluded=("/v1/licenses/activation/challenge","/v1/licenses/activation/complete",
        "/v1/gifts/claim/challenge","/v1/gifts/claim/complete","/v1/private/devices/deactivate")
    for path in excluded:
        candidates=(path,path+'/',path+'?x=1',path.replace('/activation/','//activation/'),
            path.replace('/','\\'),path+'/../challenge',path.replace('/','/%2f',1),
            path.replace('/','/%252f',1))
        for candidate in candidates:
            for method in ('GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS','TRACE'):
                assert TestClient(application,base_url='https://proxy.invalid').request(method,candidate,json={}).status_code in {400,404,405}
        raw_variants=(path.encode()+b'/',path.encode().replace(b'/',b'%2f',1),path.encode().replace(b'/',b'%252f',1),b'/other')
        for raw in raw_variants:
            status,_,_=direct_asgi(application,path=path,method='POST',headers=[(b'host',b'forged.invalid')],
                request_messages=[{'type':'http.request','body':b'{}','more_body':False}]) if raw==path.encode() else _direct_raw(application,path,raw)
            assert status in {400,404,405}
    before=authority._connect().execute('select count(*) from audit_log').fetchone()[0]
    identity=TestClient(application).get('/v1/authority/identity',headers={'host':'forged.invalid'})
    assert identity.status_code==200 and set(identity.json())=={'authority_id','key_id','generation','public_key_sha256','status'}
    after=authority._connect().execute('select count(*) from audit_log').fetchone()[0]
    assert before==after and calls==[]
    assert {route.path for route in application.routes if getattr(route,'path','').startswith('/v1/')}==expected
    assert application.openapi()['paths'].keys()==expected


def _direct_raw(application,path,raw_path):
    messages=[]
    scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"POST","scheme":"https",
        "path":path,"raw_path":raw_path,"query_string":b"","root_path":"/mounted","headers":[(b'host',b'proxy.invalid'),(b'content-length',b'2'),(b'content-type',b'application/json')],
        "client":("127.0.0.1",1),"server":("proxy.invalid",443)}
    frames=[{"type":"http.request","body":b"{}","more_body":False}]
    async def receive(): return frames.pop(0) if frames else {"type":"http.disconnect"}
    async def send(message): messages.append(message)
    asyncio.run(application(scope,receive,send))
    return next(m['status'] for m in messages if m['type']=='http.response.start'),{},b''


def test_service_only_route_policy_is_exact_closed_surface_and_excluded_methods_never_run(authority, monkeypatch):
    calls=[]
    for name in ('issue_activation_challenge','activate_challenge','deactivate'):
        monkeypatch.setattr(authority,name,lambda *a,_name=name,**k:calls.append(_name))
    application=app(authority,route_policy='service-only')
    expected={"/v1/authority/identity","/v1/service/entitlements","/v1/service/entitlements/read",
        "/v1/service/revocations","/v1/service/revocations/read"}
    assert {route.path for route in application.routes if getattr(route,'path','').startswith('/v1/')}==expected
    client=TestClient(application)
    excluded=("/v1/licenses/activation/challenge","/v1/licenses/activation/complete",
        "/v1/gifts/claim/challenge","/v1/gifts/claim/complete","/v1/private/devices/deactivate")
    for path in excluded:
        for candidate in (path,path+'/',path+'?x=1',path.replace('/activation/','//activation/')):
            for method in ('GET','POST','PUT','PATCH','DELETE'):
                assert client.request(method,candidate,json={}).status_code in {404,405}
    assert calls==[]
    for path in ('/docs','/redoc','/openapi.json'):
        assert client.get(path).status_code==404
    with pytest.raises(RuntimeError,match='composition invalid'):
        create_authority_app(authority=authority,route_policy='service-only-alias')


def test_every_route_has_a_closed_response_model(authority):
    application = app(authority)
    expected = {"/v1/authority/identity", "/v1/licenses/activation/challenge",
        "/v1/licenses/activation/complete", "/v1/gifts/claim/challenge", "/v1/gifts/claim/complete",
        "/v1/service/entitlements", "/v1/service/entitlements/read", "/v1/service/revocations",
        "/v1/service/revocations/read", "/v1/private/devices/deactivate"}
    routes = {route.path: route for route in application.routes if route.path in expected}
    assert set(routes) == expected
    assert all(route.response_model is not None for route in routes.values())
    assert all(route.response_model.model_config.get("extra") == "forbid" for route in routes.values())


def test_duplicate_case_colliding_json_and_headers_and_bounds(authority):
    client = TestClient(app(authority)); path = "/v1/service/entitlements"; value = entitlement(authority)
    raw = json.dumps(value).encode(); headers = service_headers(authority, path, raw)
    for payload in (b'{"license_id":"a","License_Id":"b","device_public_key":"x"}', b'{"a":1,"a":2}'):
        assert_generic(client.post("/v1/licenses/activation/challenge", content=payload), 400)
    duplicated = [(k.lower(), v) for k, v in headers.items()] + [("X-Authority-Nonce", "different")]
    result = client.post(path, content=raw, headers=Headers(raw=[(k.encode(), v.encode()) for k, v in duplicated]))
    assert_generic(result, 400)
    assert_generic(client.post(path, content=b"x" * 16385, headers={"content-type": "application/json"}), 413)
    too_many = Headers(raw=[(f"x-{i}".encode(), b"v") for i in range(65)])
    assert_generic(client.get("/v1/authority/identity", headers=too_many), 400)
    assert_generic(client.get("/v1/authority/identity", headers={"x-long": "v" * 4097}), 400)
    with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0] == 0


def test_owner_admin_denial_missing_verifier_and_side_effect_before_auth_zero(authority):
    license_id = authority.create_license()["license_id"]
    body = {"license_id": license_id, "device_id": "gmdev_" + "a" * 64}
    raw = json.dumps(body).encode()
    missing = TestClient(app(authority, owner_verifier=None)).post("/v1/private/devices/deactivate", content=raw, headers={"Authorization": "Owner proof"})
    assert_generic(missing, 503)
    verifier = OwnerVerifier(False); denied = TestClient(app(authority, owner_verifier=verifier)).post("/v1/private/devices/deactivate", content=raw, headers={"Authorization": "Owner proof"})
    assert_generic(denied, 403); assert verifier.calls == 1
    with authority._connect() as db: assert db.execute("select count(*) from audit_log where event='device_deactivated'").fetchone()[0] == 0


def test_public_payment_and_gift_contracts_are_generic_and_sensitive_safe(authority):
    client = TestClient(app(authority)); key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    license_id = authority.create_license()["license_id"]
    challenge = client.post("/v1/licenses/activation/challenge", json={"license_id": license_id, "device_public_key": public})
    assert challenge.status_code == 200; value = challenge.json()["challenge"]
    proof = base64.b64encode(key.sign(activation_challenge(license_id, public, value["nonce"]))).decode()
    complete = client.post("/v1/licenses/activation/complete", json={"challenge_id": value["challenge_id"], "proof": proof})
    assert complete.status_code == 200 and complete.json()["certificate"]["license_id"] == license_id
    gift = authority.create_gift(); bad = client.post("/v1/gifts/claim/challenge", json={"claim_key": gift["claim_key"] + "x", "device_public_key": public})
    assert_generic(bad, 404); assert gift["claim_key"] not in bad.text
    malformed = client.post("/v1/licenses/activation/complete", json={"challenge_id": "SECRET_CAPABILITY", "proof": "SECRET_PROOF"})
    assert_generic(malformed, 400)


def test_verifier_exceptions_never_become_response_or_log_sink(authority, caplog):
    client = TestClient(app(authority, service_verifier=ServiceVerifier(authority, explode=True)))
    response = post_service(client, authority, "/v1/service/entitlements", entitlement(authority))
    assert_generic(response, 403)
    captured = caplog.text
    assert "SECRET_SERVICE_TOKEN" not in captured and "payload_digest" not in captured and "111111" not in captured

@pytest.mark.parametrize("field,value", [
    ("key_id", "other-key"), ("generation", 2),
    ("public_key_sha256", "0" * 64), ("attestation", "other-anchor"),
    ("authority_id", "other-authority"),
])
@pytest.mark.parametrize("path,make", [
    ("/v1/service/entitlements", entitlement),
    ("/v1/service/entitlements/read", read_request),
    ("/v1/service/revocations/read", read_request),
])
def test_body_identity_mismatch_precedes_verifier_and_does_not_burn_nonce(authority, field, value, path, make):
    replay = Replay(); verifier = ServiceVerifier(authority); application = app(authority, replay_store=replay, service_verifier=verifier)
    client = TestClient(application); body = make(authority)
    if field == "authority_id": body["authority_id"] = value
    else: body["signer_identity"] = body["signer_identity"] | {field: value}
    assert_generic(post_service(client, authority, path, body), 403)
    assert verifier.calls == [] and replay.values == set()
    good = make(authority)
    result = post_service(client, authority, path, good)
    if path.endswith("/read"):
        assert_generic(result, 404)  # nonce was accepted; Authority lookup is the first failure
        assert replay.values
    else:
        assert result.status_code == 200 and replay.values


def test_revocation_identity_mismatch_does_not_burn_nonce(authority):
    replay = Replay(); verifier = ServiceVerifier(authority); client = TestClient(app(authority, replay_store=replay, service_verifier=verifier))
    body = {"source":"payments", "source_id":"1"*64, "payload_digest":"2"*64,
        "authority_id":authority.authority_id, "signer_identity":authority.handshake() | {"generation":2},
        "license_id":"gm_"+"a"*32, "action":"revoke", "reason":"administrative",
        "payment_proof":"3"*64, "tx_hash":"0x"+"4"*64, "created_at":"2026-08-08T05:00:00Z"}
    assert_generic(post_service(client, authority, "/v1/service/revocations", body), 403)
    assert verifier.calls == [] and replay.values == set()


@pytest.mark.parametrize("payload", [
    b'{"license_id":"gm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","device_public_key":"x","\xc3\xa9":1,"e\xcc\x81":2}',
    b'{"license_id":"gm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","device_public_key":NaN}',
    b'{"license_id":"gm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","device_public_key":Infinity}',
    b'{"license_id":"gm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","device_public_key":-Infinity}',
    b'{"license_id":"gm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","device_public_key":9223372036854775808}',
])
def test_unicode_constants_and_integer_abuse_are_generic(authority, payload):
    assert_generic(TestClient(app(authority)).post("/v1/licenses/activation/challenge", content=payload), 400)


def test_depth_nodes_and_string_abuse_are_generic(authority):
    client = TestClient(app(authority)); path = "/v1/licenses/activation/challenge"
    deep = json.dumps({"license_id":"gm_"+"a"*32,"device_public_key":"x","extra":[[[[[[[[[1]]]]]]]]]}).encode()
    nodes = json.dumps({"license_id":"gm_"+"a"*32,"device_public_key":"x","extra":[0]*129}).encode()
    string = json.dumps({"license_id":"gm_"+"a"*32,"device_public_key":"x"*4097}).encode()
    for payload in (deep, nodes, string): assert_generic(client.post(path, content=payload), 400)


def test_framework_errors_docs_queries_raw_path_and_aware_clock(authority):
    client = TestClient(app(authority))
    for path in ("/docs", "/redoc", "/openapi.json", "/missing"):
        assert_generic(client.get(path), 404)
    assert_generic(client.get("/v1/licenses/activation/challenge"), 405)
    public_query = client.get("/v1/authority/identity?bad=%ZZ")  # public identity ignores query
    assert public_query.status_code == 200
    body = entitlement(authority); raw = json.dumps(body).encode()
    assert_generic(client.post("/v1/service/entitlements?x=1", content=raw, headers=service_headers(authority,"/v1/service/entitlements",raw)), 400)
    assert_generic(client.post("/v1/service/%65ntitlements", content=raw, headers=service_headers(authority,"/v1/service/entitlements",raw)), 400)
    with pytest.raises(RuntimeError, match="clock unavailable"):
        app(authority, now=lambda: datetime(2026, 8, 8))
    broken = app(authority)
    @broken.get("/test-only-explode")
    async def explode(): raise RuntimeError("SECRET_500")
    assert_generic(TestClient(broken, raise_server_exceptions=False).get("/test-only-explode"), 500)


def test_descriptor_model_constraints():
    base = {"authority_id":"authority-test", "key_id":"fixture-key", "generation":1,
        "public_key_sha256":"a"*64, "attestation":"fixture:ephemeral"}
    from licensing.authority_api import SignerIdentity
    assert SignerIdentity.model_validate(base).generation == 1
    for change in ({"generation":0}, {"public_key_sha256":"A"*64}, {"attestation":"雪"}, {"key_id":"x"}):
        with pytest.raises(Exception): SignerIdentity.model_validate(base | change)
