"""Real PaymentService request builders -> authenticated Authority ASGI transport."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from licensing.authority_api import PeerDescriptor, ServiceIdentity, create_authority_app
from test_device_activation_closure import paid, setup


class Descriptor:
    def __init__(self, authority): self.authority = authority
    def descriptor(self): return self.authority.handshake() | {"status": "active"}


class Anchor:
    def verify(self, _descriptor): return True


class Replay:
    def __init__(self): self.values = set()
    def consume(self, subject, nonce, timestamp):
        value = (subject, nonce, timestamp)
        if value in self.values: return False
        self.values.add(value); return True


class Verifier:
    def verify(self, request):
        expected = hashlib.sha256((request.method + "\0" + request.path + "\0" + request.body_sha256 + "\0" + request.timestamp + "\0" + request.nonce + "\0" + request.audience + "\0" + request.authority_id).encode()).hexdigest().encode()
        if request.credential != expected: return None
        return ServiceIdentity("payments", request.audience, request.authority_id)


class PaymentAuthorityHttpAdapter:
    """Test adapter whose kwargs are supplied exclusively by real PaymentService builders."""
    PATHS = {
        "create_external_entitlement": "/v1/service/entitlements",
        "read_external_entitlement_acknowledgement": "/v1/service/entitlements/read",
        "revoke_external_entitlement": "/v1/service/revocations",
        "read_external_revocation_acknowledgement": "/v1/service/revocations/read",
    }
    def __init__(self, authority):
        self.authority = authority; self.operation_calls = []
        application = create_authority_app(authority=authority, service_verifier=Verifier(), replay_store=Replay(),
            signer_descriptor_provider=Descriptor(authority), anchor_verifier=Anchor(),
            peer_resolver=lambda _request: PeerDescriptor("payments-fixture"), now=lambda: datetime.now(timezone.utc))
        self.client = TestClient(application)
    def handshake(self):
        response = self.client.get("/v1/authority/identity")
        assert response.status_code == 200, response.text
        # PaymentService's signer pin includes attestation, intentionally omitted by public identity.
        public = response.json(); public.pop("status")
        return public | {"attestation": self.authority.handshake()["attestation"]}
    def _post(self, operation, body):
        self.operation_calls.append(operation); path = self.PATHS[operation]
        raw = json.dumps(body, separators=(",", ":")).encode()
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        nonce = f"paymentnonce{len(self.operation_calls):04d}"
        digest = hashlib.sha256(raw).hexdigest(); audience = "growthmap-authority"; authority_id = self.authority.authority_id
        proof = hashlib.sha256(("POST\0" + path + "\0" + digest + "\0" + timestamp + "\0" + nonce + "\0" + audience + "\0" + authority_id).encode()).hexdigest()
        response = self.client.post(path, content=raw, headers={"Content-Type": "application/json", "X-Authority-Service-Auth": proof,
            "X-Authority-Timestamp": timestamp, "X-Authority-Nonce": nonce, "X-Authority-Audience": audience, "X-Authority-Id": authority_id})
        assert response.status_code == 200, response.text
        return response.json()
    def create_external_entitlement(self, **body): return self._post("create_external_entitlement", body)
    def read_external_entitlement_acknowledgement(self, **body): return self._post("read_external_entitlement_acknowledgement", body | {"authority_id": self.authority.authority_id})
    def revoke_external_entitlement(self, **body): return self._post("revoke_external_entitlement", body)
    def read_external_revocation_acknowledgement(self, **body): return self._post("read_external_revocation_acknowledgement", body | {"authority_id": self.authority.authority_id})


def test_real_payment_create_read_revoke_read_http_and_signature_verification(tmp_path):
    service, authority, _ = setup(tmp_path); order = paid(service); adapter = PaymentAuthorityHttpAdapter(authority)
    entitlement = service.deliver_entitlement(order["order_id"], adapter)
    assert entitlement["delivery_receipt"] and adapter.operation_calls[:2] == [
        "create_external_entitlement", "read_external_entitlement_acknowledgement"]
    service.admin_transition(order["order_id"], "revoke")
    receipt = service.deliver_revocation(order["order_id"], adapter)
    assert receipt["revocation_receipt"] and adapter.operation_calls[-2:] == [
        "revoke_external_entitlement", "read_external_revocation_acknowledgement"]


def test_real_payment_revocation_builder_accepts_both_utc_forms(tmp_path):
    instant = datetime.now(timezone.utc).replace(microsecond=0)
    utc_forms = (instant.isoformat().replace("+00:00", "Z"), instant.isoformat())
    for index, stamp in enumerate(utc_forms):
        case = tmp_path / str(index); case.mkdir()
        service, authority, _ = setup(case); order = paid(service)
        service.deliver_entitlement(order["order_id"], authority); service.admin_transition(order["order_id"], "revoke")
        claimed = service.claim_revocation("http-adapter", order_id=order["order_id"]); claimed["created_at"] = stamp
        adapter = PaymentAuthorityHttpAdapter(authority)
        result = service.deliver_claimed_revocation(claimed, adapter, "http-adapter")
        assert adapter.operation_calls == ["revoke_external_entitlement", "read_external_revocation_acknowledgement"]
        assert result["revocation_receipt"]
        with authority._connect() as db:
            assert db.execute("select event_created_at from external_revocations").fetchone()[0] == stamp
