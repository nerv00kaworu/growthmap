"""Offline-only fixtures for the authenticated provider/reconciler seams."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from growthmap_payments.api import MockFacilitator, create_app
from growthmap_payments.facilitator import OfficialX402Facilitator
from growthmap_payments.finality import AuthenticatedFinalityReconciler, canonical_payload, sign_test_document
from growthmap_payments.public_config import APPROVED_BASE_RECIPIENT
from growthmap_payments.service import BASE_NETWORK, BASE_USDC, PaymentService
from test_payments import HEAD, MAC_KEY, RECIPIENT, config

PAYER = "0x" + "2" * 40
TX = "0x" + "3" * 64
FIXED_NOW = datetime(2090, 8, 2, tzinfo=timezone.utc)


class OfflineProvider:
    """Test-only byte source; it is deliberately not a production credential/provider."""
    def __init__(self, document=b""):
        self.document = document

    def finality_evidence(self, intent):
        return self.document


def prepared(tmp_path, name="finality"):
    service = PaymentService(config(tmp_path / f"{name}.sqlite"))
    order = service.create_order("x402", f"{name}@e.test")
    intent = service.prepare_x402_intent(order["order_id"], f"proof-{name}", f"nonce-{name}", 10_000_000, PAYER)
    service.mark_intent_ambiguous(intent["intent_id"], "offline fixture")
    with service._db() as db:
        row = dict(db.execute("SELECT * FROM settlement_intents WHERE intent_id=?", (intent["intent_id"],)).fetchone())
    return service, row


def payload(intent, outcome="paid", **changes):
    value = {
        "outcome": outcome,
        "proof_hash": intent["proof_hash"],
        "nonce_hash": intent["nonce_hash"],
        "order_id": intent["order_id"],
        "payer": intent["verified_payer"],
        "tx_hash": TX if outcome == "paid" else "",
        "evidence_hash": hashlib.sha256(("receipt:" + intent["intent_id"] + outcome).encode()).hexdigest(),
        "source": "offline.fixture.finality",
        "finality_at": intent["created_at"],
        "finality_basis": "provider.receipt.confirmed",
        "network": BASE_NETWORK,
        "asset": BASE_USDC.lower(),
        "payee": RECIPIENT.lower(),
        "amount_minor": intent["amount_minor"],
    }
    value.update(changes)
    return value


def reconciler(provider):
    return AuthenticatedFinalityReconciler(provider, MAC_KEY, payee=RECIPIENT, now=lambda: FIXED_NOW)


def test_valid_authenticated_paid_and_unpaid(tmp_path):
    paid_service, paid_intent = prepared(tmp_path, "paid")
    paid_provider = OfflineProvider(sign_test_document(payload(paid_intent), MAC_KEY))
    result = paid_service.reconcile_intent(paid_intent["intent_id"], reconciler(paid_provider), "admin-fixture")
    assert result["state"] == "payment_confirmed" and result["tx_hash"] == TX

    unpaid_service, unpaid_intent = prepared(tmp_path, "unpaid")
    unpaid_provider = OfflineProvider(sign_test_document(payload(unpaid_intent, "unpaid"), MAC_KEY))
    result = unpaid_service.reconcile_intent(unpaid_intent["intent_id"], reconciler(unpaid_provider), "admin-fixture")
    assert result["state"] == "cancelled_unpaid"


@pytest.mark.parametrize("field,bad", [
    ("outcome", "unknown"), ("proof_hash", "0" * 64), ("nonce_hash", "1" * 64),
    ("order_id", "wrong-order"), ("payer", "0x" + "4" * 40), ("tx_hash", "0x" + "5" * 64),
    ("evidence_hash", "6" * 64), ("source", "other.source"),
    ("finality_at", "2020-07-01T00:00:00+00:00"), ("finality_basis", "other.basis"),
    ("network", "eip155:1"), ("asset", "0x" + "7" * 40),
    ("payee", "0x" + "8" * 40), ("amount_minor", 9_999_999),
])
def test_tamper_every_authenticated_field_fails_mac(tmp_path, field, bad):
    _, intent = prepared(tmp_path, "tamper-" + field)
    original = payload(intent)
    document = json.loads(sign_test_document(original, MAC_KEY))
    document["payload"][field] = bad
    provider = OfflineProvider(canonical_payload(document))
    with pytest.raises(ValueError, match="verification failed"):
        reconciler(provider).reconcile(intent)


@pytest.mark.parametrize("field,bad", [
    ("network", "eip155:1"), ("asset", "0x" + "7" * 40),
    ("payee", "0x" + "8" * 40), ("amount_minor", 1),
    ("payer", "0x" + "9" * 40), ("proof_hash", "a" * 64),
    ("nonce_hash", "b" * 64), ("order_id", "wrong"),
])
def test_authenticated_wrong_binding_is_rejected(tmp_path, field, bad):
    _, intent = prepared(tmp_path, "binding-" + field)
    provider = OfflineProvider(sign_test_document(payload(intent, **{field: bad}), MAC_KEY))
    with pytest.raises(ValueError, match="binding mismatch"):
        reconciler(provider).reconcile(intent)


def test_wrong_key_signature_schema_bounds_duplicates_and_case_collision(tmp_path):
    _, intent = prepared(tmp_path, "parsing")
    good = payload(intent)
    for raw, pattern in [
        (sign_test_document(good, b"wrong-key-material-that-is-at-least-32"), "verification failed"),
        (b"x" * 16_385, "invalid authenticated finality document"),
        (canonical_payload({"mac": "0" * 64, "payload": good, "extra": 1}), "invalid authenticated finality envelope"),
    ]:
        with pytest.raises(ValueError, match=pattern):
            reconciler(OfflineProvider(raw)).reconcile(intent)
    signed = sign_test_document(good, MAC_KEY).decode()
    duplicate = signed.replace('"mac":', '"mac":"0","mac":', 1).encode()
    collision = signed.replace('"mac":', '"MAC":"0","mac":', 1).encode()
    for raw in (duplicate, collision):
        with pytest.raises(ValueError, match="invalid authenticated finality document"):
            reconciler(OfflineProvider(raw)).reconcile(intent)
    extra = dict(good, unexpected="x")
    with pytest.raises(ValueError, match="schema"):
        reconciler(OfflineProvider(sign_test_document(extra, MAC_KEY))).reconcile(intent)
    missing = dict(good); missing.pop("source")
    with pytest.raises(ValueError, match="schema"):
        reconciler(OfflineProvider(sign_test_document(missing, MAC_KEY))).reconcile(intent)
    wrong_type = dict(good, amount_minor="10000000")
    with pytest.raises(ValueError, match="field type"):
        reconciler(OfflineProvider(sign_test_document(wrong_type, MAC_KEY))).reconcile(intent)


@pytest.mark.parametrize("stamp", ["2026-08-01T23:59:00", "2026-08-01T23:59:00Z", "2026-08-01T23:59:00+08:00", "2090-08-02T00:00:01+00:00"])
def test_naive_non_utc_and_future_timestamp_rejected(tmp_path, stamp):
    _, intent = prepared(tmp_path, "time-" + hashlib.sha256(stamp.encode()).hexdigest()[:8])
    provider = OfflineProvider(sign_test_document(payload(intent, finality_at=stamp), MAC_KEY))
    with pytest.raises(ValueError, match="timestamp"):
        reconciler(provider).reconcile(intent)


@pytest.mark.parametrize("outcome,tx", [("paid", ""), ("unpaid", TX)])
def test_transaction_must_match_exact_outcome(tmp_path, outcome, tx):
    _, intent = prepared(tmp_path, "outcome-" + outcome)
    provider = OfflineProvider(sign_test_document(payload(intent, outcome, tx_hash=tx), MAC_KEY))
    with pytest.raises(ValueError, match="transaction outcome"):
        reconciler(provider).reconcile(intent)


def test_authenticated_evidence_replay_conflict_and_race_fail_closed(tmp_path):
    service, first = prepared(tmp_path, "replay-first")
    order = service.create_order("x402", "replay-second@e.test")
    second_id = service.prepare_x402_intent(order["order_id"], "proof-second", "nonce-second", 10_000_000, PAYER)["intent_id"]
    service.mark_intent_ambiguous(second_id, "fixture")
    with service._db() as db:
        second = dict(db.execute("SELECT * FROM settlement_intents WHERE intent_id=?", (second_id,)).fetchone())
    first_doc = payload(first)
    service.reconcile_intent(first["intent_id"], reconciler(OfflineProvider(sign_test_document(first_doc, MAC_KEY))), "admin-fixture")
    replay = payload(second, evidence_hash=first_doc["evidence_hash"])
    with pytest.raises(ValueError, match="already used"):
        service.reconcile_intent(second_id, reconciler(OfflineProvider(sign_test_document(replay, MAC_KEY))), "admin-fixture")
    conflict = payload(second, tx_hash="0x" + "c" * 64)
    provider = OfflineProvider(sign_test_document(conflict, MAC_KEY))
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(service.reconcile_intent, second_id, reconciler(provider), "admin-fixture") for _ in range(2)]
    assert sum(f.exception() is None for f in futures) == 1
    assert sum(isinstance(f.exception(), ValueError) for f in futures) == 1


def test_admin_reconcile_without_adapter_is_503(tmp_path):
    service, intent = prepared(tmp_path, "api-503")
    client = TestClient(create_app(service.config, MockFacilitator()))
    response = client.post(f"/v1/admin/intents/{intent['intent_id']}/reconcile", headers=HEAD)
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"


def test_official_client_provider_seam_and_production_hard_block(tmp_path):
    class Client:
        def verify(self, *args): pass
        def settle(self, *args): pass
    class Provider:
        def __init__(self): self.calls = []
        def build_x402_client(self, **kwargs): self.calls.append(kwargs); return Client()
    provider = Provider()
    official = OfficialX402Facilitator.from_client_provider(
        "https://facilitator.test", provider, allowed_origin="https://facilitator.test", _allow_test_origin=True
    )
    assert isinstance(official.client, Client) and provider.calls == [{"endpoint": "https://facilitator.test", "timeout": 20.0}]
    with pytest.raises(RuntimeError, match="invalid client"):
        OfficialX402Facilitator.from_client_provider(
            "https://facilitator.test", type("Bad", (), {"build_x402_client": lambda *a, **k: object()})(),
            _allow_test_origin=True,
        )
    production = replace(
        config(tmp_path / "production.sqlite"), recipient=APPROVED_BASE_RECIPIENT,
        production=True, admin_secret_hash="$argon2id$fixture",
    )
    candidates = [
        None,
        official,
        OfficialX402Facilitator("https://facilitator.test", client=Client(), _allow_test_origin=True),
        type("Forged", (OfficialX402Facilitator,), {}) (
            "https://facilitator.test", client=Client(), _allow_test_origin=True
        ),
    ]
    for candidate in candidates:
        if candidate is not None:
            candidate._authorized_provider_injected = True
        with pytest.raises(RuntimeError, match="reviewed Argon2id session provider not integrated"):
            create_app(production, candidate, reconciler=object())


@pytest.mark.parametrize("endpoint", [
    "http://facilitator.offline-fixture.dev", "https://127.0.0.1", "https://[::1]", "https://localhost",
    "https://foo.local", "https://foo_internal.offline-fixture.dev", "https://offline-fixture.dev.",
    "https://offline-fixture.dev:443", "https://offline-fixture.dev:8443", "https://offline-fixture.dev:bad",
    "https://offline-fixture.dev:99999", "https://offline-fixture.dev:", "https://u@offline-fixture.dev",
    "https://offline-fixture.dev/", "https://offline-fixture.dev/path", "https://offline-fixture.dev?q=1",
    "https://offline-fixture.dev#x", "https://OFFLINE-FIXTURE.dev", "https://facilitator.test",
    "https://[::1", "https://[:::1]", "https://[not-an-ip]",
    "https://example.com", "https://api.example.com", "https://example.net", "https://api.example.net",
    "https://example.org", "https://api.example.org", "https://home.arpa", "https://host.home.arpa",
    "https://thing.onion", "https://deep.thing.onion", "https://foo.invalid", "https://foo.example",
    "https://foo.internal", "https://alt", "https://foo.alt", "https://deep.foo.alt",
    "https://arpa", "https://foo.arpa", "https://deep.foo.arpa", "https://10.in-addr.arpa",
    "https://168.192.in-addr.arpa", "https://d.f.ip6.arpa", "https://ipv4only.arpa",
    "https://empty.as112.arpa", "https://resolver.arpa",
    "https://xn--e1afmkfd.xn--p1ai", "https://xn--80ak6aa92e.com",
    "https://safe.xn--p1ai", "https://xn--label.safe.dev", "https://safe.xn--label.dev",
    "https://例子.com", "https://%78n--label.example.dev", "https://Xn--label.example.dev",
    "https://127.1", "https://127.0.1", "https://0177.0.0.1", "https://0x7f.0.0.1",
    "https://0x7f.1", "https://2130706433", "https://017700000001", "https://0x7f000001",
    "https://1.2.65535", "https://1.16777215", "https://4294967296", "https://999.999.999.999",
    "HTTPS://offline-fixture.dev",
])
def test_facilitator_origin_rejects_noncanonical_or_nonpublic(endpoint):
    with pytest.raises(RuntimeError, match="^facilitator endpoint must be a canonical public-DNS HTTPS origin$") as caught:
        OfficialX402Facilitator(endpoint, client=object())
    assert endpoint not in str(caught.value)


def test_facilitator_origin_rejects_every_ascii_whitespace_control_before_parsing():
    origin = "https://offline-fixture.dev"
    for codepoint in (*range(0x21), 0x7F):
        character = chr(codepoint)
        for endpoint in (character + origin, origin + character, "https://offline" + character + "-fixture.dev"):
            with pytest.raises(RuntimeError, match="^facilitator endpoint must be a canonical public-DNS HTTPS origin$") as caught:
                OfficialX402Facilitator(endpoint, client=object())
            assert str(caught.value) == "facilitator endpoint must be a canonical public-DNS HTTPS origin"
        for allowed_origin in (character + origin, origin + character, "https://offline" + character + "-fixture.dev"):
            with pytest.raises(RuntimeError, match="^facilitator endpoint must be a canonical public-DNS HTTPS origin$") as caught:
                OfficialX402Facilitator(origin, client=object(), allowed_origin=allowed_origin)
            assert str(caught.value) == "facilitator endpoint must be a canonical public-DNS HTTPS origin"


def test_facilitator_origin_legacy_numeric_negative_controls_are_dns_names():
    for origin in (
        "https://127.1.offline-fixture.dev", "https://0x7f.offline-fixture.dev",
        "https://0177-name.offline-fixture.dev", "https://4294967296.offline-fixture.dev",
    ):
        assert OfficialX402Facilitator(origin, client=object()).endpoint == origin


def test_facilitator_origin_exact_allowed_origin_and_test_isolation():
    fixture_origin = "https://facilitator.offline-fixture.dev"
    adapter = OfficialX402Facilitator(fixture_origin, client=object(), allowed_origin=fixture_origin)
    assert adapter.endpoint == fixture_origin
    adversarial_allowed_origins = (
        "https://other.offline-fixture.dev", "https://foo.arpa", "https://xn--label.safe.dev",
        "https://ALLOWED.offline-fixture.dev", "https://allowed.offline-fixture.dev/%66oo",
        "HTTPS://facilitator.offline-fixture.dev", "https://facilitator.offline-fixture.dev/",
        "https://127.1", "https://127.0.1", "https://0177.0.0.1", "https://0x7f.0.0.1",
        "https://0x7f.1", "\nhttps://facilitator.offline-fixture.dev",
        "https://facili\ttator.offline-fixture.dev", "https://facilitator.offline-fixture.dev\r",
    )
    for allowed_origin in adversarial_allowed_origins:
        with pytest.raises(RuntimeError, match="^facilitator endpoint must be a canonical public-DNS HTTPS origin$") as caught:
            OfficialX402Facilitator(fixture_origin, client=object(), allowed_origin=allowed_origin)
        assert str(caught.value) == "facilitator endpoint must be a canonical public-DNS HTTPS origin"
    with pytest.raises(RuntimeError, match="^facilitator endpoint must be a canonical public-DNS HTTPS origin$"):
        OfficialX402Facilitator(
            "https://facilitator.test", client=object(), allowed_origin="https://facilitator.test"
        )
    assert OfficialX402Facilitator(
        "https://facilitator.test", client=object(), allowed_origin="https://facilitator.test",
        _allow_test_origin=True,
    ).endpoint == "https://facilitator.test"


def test_finality_pre_intent_boundary_noncanonical_and_bad_intent_clock(tmp_path):
    _, intent = prepared(tmp_path, "clock")
    created = datetime.fromisoformat(intent["created_at"])
    cases = [
        ((created - timedelta(microseconds=1)).isoformat(), intent, False),
        (intent["created_at"], intent, True),
        (intent["created_at"].replace("+00:00", "Z"), intent, False),
        (intent["created_at"], dict(intent, created_at="not-a-time"), False),
        (intent["created_at"], dict(intent, created_at=intent["created_at"].replace("+00:00", "Z")), False),
    ]
    for stamp, candidate, valid in cases:
        provider = OfflineProvider(sign_test_document(payload(intent, finality_at=stamp), MAC_KEY))
        if valid:
            assert reconciler(provider).reconcile(candidate)["finality_at"] == stamp
        else:
            with pytest.raises(ValueError, match="timestamp"):
                reconciler(provider).reconcile(candidate)


@pytest.mark.parametrize("stamp,valid", [
    ("2080-08-02T00:00:00+00:00", True),
    ("2080-08-02T00:00:00.123456+00:00", True),
    ("2080-08-02T00:00:00.0+00:00", False),
    ("2080-08-02T00:00:00.00+00:00", False),
    ("2080-08-02T00:00:00.000000+00:00", False),
    ("2080-08-02T00:00:00.1+00:00", False),
    ("2080-08-02T00:00:00.12345+00:00", False),
])
def test_finality_and_durable_created_at_use_exact_isoformat_round_trip(tmp_path, stamp, valid):
    _, intent = prepared(tmp_path, "canonical-" + hashlib.sha256(stamp.encode()).hexdigest()[:8])
    candidate = dict(intent, created_at=stamp)
    provider = OfflineProvider(sign_test_document(payload(intent, finality_at=stamp), MAC_KEY))
    if valid:
        assert reconciler(provider).reconcile(candidate)["finality_at"] == stamp
    else:
        with pytest.raises(ValueError, match="timestamp"):
            reconciler(provider).reconcile(candidate)


@pytest.mark.parametrize("created_at", [
    "2080-08-02T00:00:00.0+00:00", "2080-08-02T00:00:00.00+00:00",
    "2080-08-02T00:00:00.000000+00:00", "2080-08-02T00:00:00.1+00:00",
    "2080-08-02T00:00:00.12345+00:00",
])
def test_noncanonical_durable_created_at_rejected_even_with_canonical_finality(tmp_path, created_at):
    _, intent = prepared(tmp_path, "created-" + hashlib.sha256(created_at.encode()).hexdigest()[:8])
    provider = OfflineProvider(sign_test_document(
        payload(intent, finality_at="2080-08-02T00:00:00.123456+00:00"), MAC_KEY
    ))
    with pytest.raises(ValueError, match="timestamp"):
        reconciler(provider).reconcile(dict(intent, created_at=created_at))


def test_deep_json_and_provider_exception_are_stable(tmp_path):
    _, intent = prepared(tmp_path, "depth")
    good = payload(intent)
    nested = good
    for _ in range(40):
        nested = {"x": nested}
    raw = canonical_payload({"mac": "0" * 64, "payload": nested})
    with pytest.raises(ValueError, match="invalid authenticated finality document"):
        reconciler(OfflineProvider(raw)).reconcile(intent)

    class Exploding:
        def finality_evidence(self, intent):
            raise RuntimeError("provider-secret-message")
    with pytest.raises(ValueError, match="^authenticated finality provider unavailable$") as caught:
        reconciler(Exploding()).reconcile(intent)
    assert "provider-secret-message" not in str(caught.value)


def test_unpaid_persistence_restart_checkpoint_conflict_and_trigger(tmp_path):
    service, intent = prepared(tmp_path, "unpaid-restart")
    doc = sign_test_document(payload(intent, "unpaid"), MAC_KEY)
    service.reconcile_intent(intent["intent_id"], reconciler(OfflineProvider(doc)), "admin-fixture")
    with service._db() as db:
        row = dict(db.execute("SELECT * FROM settlement_intents WHERE intent_id=?", (intent["intent_id"],)).fetchone())
        assert row["settled_payer"] == PAYER and row["finality_basis"] == "provider.receipt.confirmed"
        with pytest.raises(Exception, match="terminal settlement evidence is immutable"):
            db.execute("UPDATE settlement_intents SET settled_payer=? WHERE intent_id=?", ("0x" + "4" * 40, intent["intent_id"]))
    restarted = PaymentService(service.config)
    with pytest.raises(ValueError, match="intent not reconcilable"):
        restarted.reconcile_intent(intent["intent_id"], reconciler(OfflineProvider(doc)), "admin-fixture")
    service.config.settlement_checkpoint_path.write_text("{}")
    with pytest.raises(RuntimeError, match="checkpoint"):
        PaymentService(service.config)


@pytest.mark.parametrize("field,bad", [
    ("verified_payer", "0x" + "4" * 40),
    ("settled_payer", "0x" + "4" * 40),
    ("finality_basis", "other.basis"),
    ("proof_hash", "4" * 64),
    ("evidence_source", "other.source"),
    ("created_at", "2080-01-01T00:00:00+00:00"),
])
def test_settled_to_finalized_cannot_mutate_authenticated_or_legacy_fields(tmp_path, field, bad):
    service, intent = prepared(tmp_path, "paid-trigger-" + field)
    evidence = payload(intent)
    normalized = reconciler(OfflineProvider(sign_test_document(evidence, MAC_KEY))).reconcile(intent)
    service.record_settlement_result(
        intent["intent_id"], normalized["tx_hash"], normalized["evidence_hash"], normalized["source"],
        normalized["finality_at"], "admin-fixture", payer=normalized["payer"],
        finality_basis=normalized["finality_basis"],
    )
    with service._db() as db:
        with pytest.raises(Exception, match="terminal settlement evidence is immutable"):
            db.execute(
                f"UPDATE settlement_intents SET state='finalized_paid', {field}=? WHERE intent_id=?",
                (bad, intent["intent_id"]),
            )


def test_provider_exception_maps_to_api_409_without_provider_message(tmp_path, caplog):
    service, intent = prepared(tmp_path, "api-provider-error")
    class ExplodingProvider:
        def finality_evidence(self, intent):
            raise RuntimeError("provider-secret-message")
    live_reconciler = reconciler(ExplodingProvider())
    client = TestClient(create_app(service.config, MockFacilitator(), reconciler=live_reconciler))
    response = client.post(f"/v1/admin/intents/{intent['intent_id']}/reconcile", headers=HEAD)
    assert response.status_code == 409
    assert response.json() == {"detail": "authenticated finality provider unavailable"}
    assert "provider-secret-message" not in response.text
    assert "provider-secret-message" not in caplog.text
