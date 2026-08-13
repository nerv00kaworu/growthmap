import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from growthmap_payments.authority_http import SignedAuthorityHTTPAdapter
from growthmap_payments.whop_fulfillment import Worker

IDENTITY = {"authority_id": "growthmap-authority-primary", "key_id": "issuer-1", "generation": 1,
            "public_key_sha256": "a" * 64, "attestation": "kms:production"}


class Authority:
    def __init__(self): self.entitlements = {}; self.revocations = []; self.fail = False
    def handshake(self): return dict(IDENTITY)
    def create_external_entitlement(self, **body):
        if self.fail: raise OSError("private transport detail")
        self.entitlements.setdefault(body["source_id"], "gml_" + body["source_id"][:32])
        return {"license_id": self.entitlements[body["source_id"]]}
    def read_external_entitlement_acknowledgement(self, **body):
        return {"source": "whop", "source_id": body["source_id"], "license_id": self.entitlements[body["source_id"]]}
    def revoke_external_entitlement(self, **body):
        if self.fail: raise OSError("private transport detail")
        self.revocations.append(body); return {"license_id": body["license_id"]}
    def read_external_revocation_acknowledgement(self, **body):
        license_id = self.entitlements[body["source_id"]]
        return {"source": "whop", "source_id": body["source_id"], "license_id": license_id}


def setup(tmp_path, authority=None):
    path = tmp_path / "inbox.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE inbox(webhook_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,payload_sha256 TEXT NOT NULL,payload BLOB NOT NULL,status TEXT NOT NULL)")
    worker = Worker(path, authority or Authority()); worker.initialize(); return worker


def envelope(event_id, event_type="payment.succeeded", payment_id="pay_1", *, early=False, status=None, amount=None):
    product = "prod_PvObOc5wfatCY" if early else "prod_Lrwhtxe2bDQDD"
    plan = "plan_rjuSiGxXCweMF" if early else "plan_BIaeEIZ2e6OP3"
    total = amount if amount is not None else (10 if early else 29)
    status = status or {"payment.succeeded": "succeeded", "refund.created": "refunded", "dispute.created": "open"}.get(event_type, "whatever")
    payment = {"id": payment_id, "status": status, "currency": "usd", "total": total,
               "product": {"id": product}, "plan": {"id": plan}}
    data = payment if event_type == "payment.succeeded" else {"payment": payment}
    return json.dumps({"id": event_id, "type": event_type, "company_id": "biz_RVr0w7JHwRZgIq",
                       "timestamp": "2026-08-13T02:00:00Z", "data": data}, separators=(",", ":")).encode()


def insert(worker, event_id, raw, event_type="payment.succeeded", digest=None):
    with worker._db() as db:
        db.execute("INSERT INTO inbox VALUES(?,?,?,?,?)",
                   (event_id, event_type, digest or hashlib.sha256(raw).hexdigest(), raw, "verified_pending"))


def row(worker, event_id):
    with worker._db() as db: return dict(db.execute("SELECT * FROM inbox WHERE webhook_id=?", (event_id,)).fetchone())


def test_grants_personal_v1_idempotently_and_ignores_unknown_selected_event(tmp_path):
    authority = Authority(); worker = setup(tmp_path, authority)
    raw = envelope("evt_1"); insert(worker, "evt_1", raw)
    unknown = envelope("evt_2", "membership.went_valid"); insert(worker, "evt_2", unknown, "membership.went_valid")
    assert worker.run_once() == {"processed": 2, "granted": 1, "revoked": 0, "ignored": 1, "retry": 0, "failed": 0}
    assert row(worker, "evt_1")["status"] == "processed" and row(worker, "evt_2")["status"] == "processed"
    with worker._db() as db:
        grant = dict(db.execute("SELECT * FROM whop_fulfillments").fetchone())
    assert grant["state"] == "granted" and grant["tier"] == "standard" and len(authority.entitlements) == 1


def test_refund_and_dispute_revoke_only_exact_linked_license(tmp_path):
    authority = Authority(); worker = setup(tmp_path, authority)
    paid = envelope("paid", payment_id="pay_exact"); insert(worker, "paid", paid); worker.run_once()
    refund = envelope("refund", "refund.created", payment_id="pay_exact"); insert(worker, "refund", refund, "refund.created")
    assert worker.run_once()["revoked"] == 1
    assert authority.revocations[0]["action"] == "refund" and authority.revocations[0]["reason"] == "refund"
    assert authority.revocations[0]["license_id"] in authority.entitlements.values()
    missing = envelope("dispute", "dispute.created", payment_id="pay_missing"); insert(worker, "dispute", missing, "dispute.created")
    assert worker.run_once()["retry"] == 1 and row(worker, "dispute")["status"] == "verified_pending"


def test_strict_binding_and_conflicting_payment_id_fail_closed(tmp_path):
    worker = setup(tmp_path)
    wrong = envelope("wrong", amount=30); insert(worker, "wrong", wrong)
    assert worker.run_once()["failed"] == 1 and row(worker, "wrong")["status"] == "rejected"
    good = envelope("one", payment_id="same"); insert(worker, "one", good); assert worker.run_once()["granted"] == 1
    conflict = envelope("two", payment_id="same", early=True); insert(worker, "two", conflict)
    assert worker.run_once()["failed"] == 1 and row(worker, "two")["status"] == "rejected"


def test_early_first_fifty_is_atomic_under_concurrency(tmp_path):
    worker = setup(tmp_path)
    for index in range(55):
        raw = envelope(f"evt_{index}", payment_id=f"pay_{index}", early=True)
        insert(worker, f"evt_{index}", raw)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker.run_once(10), range(8)))
    with worker._db() as db:
        assert db.execute("SELECT count(*) FROM whop_fulfillments WHERE tier='early'").fetchone()[0] == 50
        states = dict(db.execute("SELECT status,count(*) FROM inbox GROUP BY status"))
    assert states == {"rejected": 5, "processed": 50}


def test_retry_is_bounded_backoff_and_error_is_digest_only(tmp_path):
    authority = Authority(); authority.fail = True
    clock = [datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc)]
    worker = Worker((tmp_path / "inbox.sqlite3"), authority, max_attempts=2, clock=lambda: clock[0])
    with sqlite3.connect(worker.db_path) as db:
        db.execute("CREATE TABLE inbox(webhook_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,payload_sha256 TEXT NOT NULL,payload BLOB NOT NULL,status TEXT NOT NULL)")
    worker.initialize(); raw = envelope("retry"); insert(worker, "retry", raw)
    assert worker.run_once()["retry"] == 1
    with worker._db() as db:
        attempt = dict(db.execute("SELECT * FROM whop_fulfillment_attempts").fetchone())
    assert attempt["attempts"] == 1 and len(attempt["last_error_digest"]) == 64
    clock[0] = datetime.fromisoformat(attempt["next_attempt_at"])
    assert worker.run_once()["failed"] == 1 and row(worker, "retry")["status"] == "rejected"


def test_payload_digest_mismatch_fails_without_authority_call(tmp_path):
    authority = Authority(); worker = setup(tmp_path, authority); raw = envelope("tamper")
    insert(worker, "tamper", raw, digest="0" * 64)
    assert worker.run_once()["failed"] == 1 and not authority.entitlements


def test_http_adapter_emits_existing_edge_signature_contract(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate(); key_file = tmp_path / "edge.pem"
    key_file.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    captured = {}
    class Headers:
        def get_content_type(self): return "application/json"
    class Response:
        status = 200; headers = Headers()
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit): return json.dumps({"license_id": "gml_123"}).encode()
    def open_request(request, timeout):
        captured.update(url=request.full_url, method=request.method, body=request.data,
                        headers={key.lower(): value for key, value in request.header_items()}, timeout=timeout)
        return Response()
    monkeypatch.setattr("growthmap_payments.authority_http.urllib.request.urlopen", open_request)
    adapter = SignedAuthorityHTTPAdapter(origin="http://127.0.0.1:8321", authority_id=IDENTITY["authority_id"],
        audience="growthmap-authority", edge_identity="payments-production", edge_source="loopback-edge",
        private_key_file=key_file, signer_identity=IDENTITY)
    body = {"source": "whop", "source_id": "b" * 64}
    assert adapter.create_external_entitlement(**body) == {"license_id": "gml_123"}
    digest = hashlib.sha256(captured["body"]).hexdigest(); headers = captured["headers"]
    statement = b"growthmap-authority-edge-v1\0" + b"\0".join(value.encode("ascii") for value in (
        "POST", "/v1/service/entitlements", digest, headers["x-authority-timestamp"],
        headers["x-authority-nonce"], "growthmap-authority", IDENTITY["authority_id"],
        "payments-production", "loopback-edge"))
    import base64
    private.public_key().verify(base64.b64decode(headers["x-authority-service-auth"]), statement)
    assert captured["url"] == "http://127.0.0.1:8321/v1/service/entitlements" and captured["timeout"] == 5.0
