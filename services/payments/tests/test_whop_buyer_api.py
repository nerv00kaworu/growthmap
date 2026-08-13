import json
from fastapi import FastAPI
from fastapi.testclient import TestClient

from growthmap_payments.whop_buyer_api import create_whop_buyer_router


class Store:
    def __init__(self): self.users = []; self.entitlement = {"license_id": "gm_" + "a" * 32}
    def list_for_verified_user(self, user_id): self.users.append(user_id); return [{"activation_key": "GM1.key"}]
    def authenticated_entitlement(self, order_id, recovery_code):
        return self.entitlement if (order_id, recovery_code) == ("order", "secret") else None


class Experience:
    def __init__(self, user_id="user_verified", access=True): self.user_id=user_id; self.access=access; self.checked=[]
    def authenticate(self, request): return {"user_id": self.user_id}
    def check_access(self, *, user_id): self.checked.append(user_id); return self.access


class Authority:
    def issue_activation_challenge(self, **body): return {"challenge_id":"c", "nonce":"n", "license_id":body["license_id"], "device_public_key":body["device_public_key"]}
    def activate_challenge(self, **body): return {"schema_version":2, "challenge_id":body["challenge_id"]}


def client(store=None, experience=None):
    app=FastAPI(); app.include_router(create_whop_buyer_router(store=store or Store(), experience=experience or Experience(), authority=Authority()))
    return TestClient(app)


def test_experience_uses_only_verified_identity_and_check_access():
    store=Store(); experience=Experience(); response=client(store,experience).get("/v1/whop/experience/licenses?user_id=attacker",headers={"X-Whop-User-Id":"attacker"})
    assert response.status_code==200 and store.users==["user_verified"] and experience.checked==["user_verified"]
    assert response.headers["cache-control"]=="no-store"


def test_experience_denies_without_access_before_querying_store():
    store=Store(); response=client(store,Experience(access=False)).get("/v1/whop/experience/licenses")
    assert response.status_code==403 and store.users==[]


def test_desktop_activation_contract_reuses_store_capability():
    c=client(); issued=c.post("/v1/activation/challenge",json={"order_id":"order","recovery_code":"secret","device_public_key":"device"})
    assert issued.status_code==200 and issued.json()["challenge"]["license_id"]=="gm_"+"a"*32
    complete=c.post("/v1/activation/complete",json={"challenge_id":"c","proof":"proof"})
    assert complete.status_code==200 and complete.json()["state"]=="activated"
    assert c.post("/v1/activation/challenge",json={"order_id":"order","recovery_code":"wrong","device_public_key":"device"}).status_code==404
