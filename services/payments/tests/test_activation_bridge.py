"""Focused signed Payments -> Authority -> desktop activation bridge tests."""
import base64
import hashlib
import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from growthmap_payments.whop_buyer_api import create_buyer_activation_router
from licensing.authority import activation_challenge
from licensing.authority_api import PeerDescriptor, ServiceIdentity, create_authority_app
from test_device_activation_closure import setup


class Descriptor:
    def __init__(self, authority): self.authority = authority
    def descriptor(self): return self.authority.handshake() | {"status": "active"}


class Anchor:
    def verify(self, _descriptor): return True


class Replay:
    def __init__(self): self.values = set()
    def consume(self, subject, nonce, timestamp):
        value=(subject,nonce,timestamp)
        if value in self.values: return False
        self.values.add(value); return True


class Verifier:
    def verify(self, request):
        statement=(request.method+"\0"+request.path+"\0"+request.body_sha256+"\0"+request.timestamp+"\0"+request.nonce+"\0"+request.audience+"\0"+request.authority_id).encode()
        if request.credential != hashlib.sha256(statement).hexdigest().encode(): return None
        return ServiceIdentity("payments",request.audience,request.authority_id)


class SignedTestAdapter:
    def __init__(self, authority):
        self.authority=authority; self.calls=[]
        self.client=TestClient(create_authority_app(authority=authority,service_verifier=Verifier(),replay_store=Replay(),signer_descriptor_provider=Descriptor(authority),anchor_verifier=Anchor(),peer_resolver=lambda _:PeerDescriptor("payments-fixture"),now=lambda:datetime.now(timezone.utc),route_policy="service-only"))
    def post(self,path,body):
        self.calls.append((path,body)); raw=json.dumps(body,separators=(",",":")).encode(); stamp=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"); nonce=f"activationnonce{len(self.calls):04d}"; digest=hashlib.sha256(raw).hexdigest(); aid=self.authority.authority_id
        proof=hashlib.sha256(("POST\0"+path+"\0"+digest+"\0"+stamp+"\0"+nonce+"\0growthmap-authority\0"+aid).encode()).hexdigest()
        response=self.client.post(path,content=raw,headers={"content-type":"application/json","x-authority-service-auth":proof,"x-authority-timestamp":stamp,"x-authority-nonce":nonce,"x-authority-audience":"growthmap-authority","x-authority-id":aid})
        assert response.status_code==200,response.text
        return response.json()
    def issue_activation_challenge(self,**body): return self.post("/v1/service/activation/challenge",body)["challenge"]
    def activate_challenge(self,*,challenge_id,proof,expected_flow_kind):
        assert expected_flow_kind=="payment"
        return self.post("/v1/service/activation/complete",{"challenge_id":challenge_id,"proof":proof})["certificate"]


class Store:
    def __init__(self, license_id): self.license_id=license_id
    def authenticated_entitlement(self,order_id,recovery_code):
        return {"id":order_id,"state":"license_issued","license_id":self.license_id} if (order_id,recovery_code)==("order","secret") else None


def test_unsigned_service_activation_is_denied_and_public_license_route_stays_closed(tmp_path):
    _,authority,_=setup(tmp_path); client=SignedTestAdapter(authority).client
    public=base64.b64encode(b"x"*32).decode()
    assert client.post("/v1/service/activation/challenge",json={"license_id":"gm_"+"a"*32,"device_public_key":public}).status_code==403
    assert client.post("/v1/licenses/activation/challenge",json={"license_id":"gm_"+"a"*32,"device_public_key":public}).status_code==404


def test_signed_bridge_wrong_recovery_and_complete_payment_flow(tmp_path):
    _,authority,_=setup(tmp_path); entitlement=authority.create_external_entitlement(source="payments",source_id="1"*64,payload_digest="2"*64,edition="personal",major_version=1,seat_limit=2,authority_id=authority.authority_id,signer_identity=authority.handshake())
    adapter=SignedTestAdapter(authority); app=FastAPI(); app.include_router(create_buyer_activation_router(store=Store(entitlement["license_id"]),authority=adapter)); desktop=TestClient(app)
    wrong=desktop.post("/v1/activation/challenge",json={"order_id":"order","recovery_code":"wrong","device_public_key":base64.b64encode(b"x"*32).decode()})
    assert wrong.status_code==404 and wrong.json()=={"state":"not_found_or_unavailable"} and wrong.headers["cache-control"]=="no-store" and adapter.calls==[]
    key=Ed25519PrivateKey.generate(); public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    issued=desktop.post("/v1/activation/challenge",json={"order_id":"order","recovery_code":"secret","device_public_key":public})
    challenge=issued.json()["challenge"]; assert issued.status_code==200 and adapter.calls[0][1]=={"license_id":entitlement["license_id"],"device_public_key":public}
    proof=base64.b64encode(key.sign(activation_challenge(entitlement["license_id"],public,challenge["nonce"]))).decode()
    completed=desktop.post("/v1/activation/complete",json={"challenge_id":challenge["challenge_id"],"proof":proof})
    assert completed.status_code==200 and completed.json()["certificate"]["license_id"]==entitlement["license_id"]
    assert adapter.calls[1][0]=="/v1/service/activation/complete" and set(adapter.calls[1][1])=={"challenge_id","proof"}
