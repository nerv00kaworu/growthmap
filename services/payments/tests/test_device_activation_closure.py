import base64, hashlib, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from growthmap_payments.api import MockFacilitator, create_app
from growthmap_payments.service import Config, PaymentService
from licensing.authority import LicenseAuthority, activation_challenge

RECIPIENT="0x1111111111111111111111111111111111111111"
def setup(tmp_path):
 key=Ed25519PrivateKey.generate();pem=tmp_path/"issuer.pem";pem.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 authority=LicenseAuthority(tmp_path/"authority.sqlite",pem);identity=authority.handshake();identity["public_key"]=authority.public_key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 cfg=Config(tmp_path/"payments.sqlite",RECIPIENT,hashlib.sha256(b"secret").hexdigest(),key,"https://admin.test","csrf","https://payments.test",isolated_test=True,settlement_mac_key=b"x"*32,settlement_checkpoint_path=tmp_path/"checkpoint",authority_id=identity["authority_id"],authority_key_id=identity["key_id"],authority_generation=identity["generation"],authority_public_key_sha256=identity["public_key_sha256"],authority_attestation=identity["attestation"],authority_public_key=identity["public_key"])
 return PaymentService(cfg),authority,cfg

def paid(service):
 order=service.create_order("x402","buyer@example.test");intent=service.prepare_x402_intent(order["order_id"],"proof","nonce",10_000_000,"0x"+"2"*40)
 service.record_settlement_result(intent["intent_id"],"0x"+"a"*64,"evidence","offline-fixture",service.now(),payer="0x"+"2"*40,finality_basis="offline_fixture");service.finalize_x402_intent(intent["intent_id"]);return order

def device(license_id):
 key=Ed25519PrivateKey.generate();public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();nonce="fresh_nonce_123456789";proof=base64.b64encode(key.sign(activation_challenge(license_id,public,nonce))).decode();return public,nonce,proof

def test_outbox_response_loss_restart_exactly_one_and_two_seats(tmp_path):
 service,authority,cfg=setup(tmp_path);order=paid(service)
 with service._db() as db: assert db.execute("select license_json from orders where id=?",(order["order_id"],)).fetchone()[0] is None
 first=service.deliver_entitlement(order["order_id"],authority);restart=PaymentService(cfg);same=restart.deliver_entitlement(order["order_id"],authority);assert same==first
 with authority._connect() as db: assert db.execute("select count(*) from external_entitlements").fetchone()[0]==1
 certs=[]
 for _ in range(2):
  public,nonce,proof=device(first["license_id"]);a=authority.activate(license_id=first["license_id"],device_public_key=public,nonce=nonce,proof=proof);b=authority.activate(license_id=first["license_id"],device_public_key=public,nonce=nonce,proof=proof);assert a==b;certs.append(a)
 public,nonce,proof=device(first["license_id"])
 try: authority.activate(license_id=first["license_id"],device_public_key=public,nonce=nonce,proof=proof)
 except ValueError as e: assert str(e)=="seat_limit_reached"
 else: raise AssertionError("third seat accepted")

def test_body_only_generic_activation_and_headers(tmp_path):
 service,authority,cfg=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);public,nonce,proof=device(ent["license_id"]);client=TestClient(create_app(cfg,MockFacilitator(),authority=authority))
 url="/v1/activation/challenge";bad=client.post(url,json={"order_id":order["order_id"],"recovery_code":"wrong","device_public_key":public});assert bad.status_code==404 and bad.json()=={"state":"not_found_or_unavailable"}
 assert order["recovery_code"] not in str(bad.request.url) and bad.headers["cache-control"]=="no-store" and bad.headers["pragma"]=="no-cache" and bad.headers["referrer-policy"]=="no-referrer"
 issued=client.post(url,json={"order_id":order["order_id"],"recovery_code":order["recovery_code"],"device_public_key":public});challenge=issued.json()["challenge"];keyproof=base64.b64encode(base64.b64decode(proof) if challenge["nonce"]==nonce else b'').decode() if False else None
 # Sign the server-issued nonce with a fresh device fixture.
 key=Ed25519PrivateKey.generate();public2=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();issued=client.post(url,json={"order_id":order["order_id"],"recovery_code":order["recovery_code"],"device_public_key":public2});challenge=issued.json()["challenge"];proof2=base64.b64encode(key.sign(activation_challenge(ent["license_id"],public2,challenge["nonce"]))).decode();good=client.post('/v1/activation/complete',json={"challenge_id":challenge["challenge_id"],"proof":proof2});again=client.post('/v1/activation/complete',json={"challenge_id":challenge["challenge_id"],"proof":proof2});assert good.status_code==200 and good.content==again.content and good.json()["certificate"]["schema_version"]==2

def test_concurrent_outbox_delivery_is_one_identity(tmp_path):
 service,authority,cfg=setup(tmp_path);order=paid(service)
 with ThreadPoolExecutor(20) as pool: ids=list(pool.map(lambda _:service.deliver_entitlement(order["order_id"],authority)["license_id"],range(100)))
 assert len(set(ids))==1

def test_deactivate_releases_seat_and_old_nonce_stays_consumed(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);devices=[]
 for _ in range(2):
  public,nonce,proof=device(ent["license_id"]);cert=authority.activate(license_id=ent["license_id"],device_public_key=public,nonce=nonce,proof=proof);devices.append((public,nonce,proof,cert))
 assert authority.deactivate(license_id=ent["license_id"],device_id=devices[0][3]["device_id"])
 public,nonce,proof=device(ent["license_id"]);assert authority.activate(license_id=ent["license_id"],device_public_key=public,nonce=nonce,proof=proof)["schema_version"]==2
 try:authority.activate(license_id=ent["license_id"],device_public_key=devices[0][0],nonce=devices[0][1],proof=devices[0][2])
 except ValueError as error:assert str(error)=="activation_nonce_consumed"
 else:raise AssertionError("deactivated nonce replay accepted")

def test_wrong_proof_does_not_consume_nonce(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);public,nonce,proof=device(ent["license_id"]);wrong=base64.b64encode(b"x"*64).decode()
 try:authority.activate(license_id=ent["license_id"],device_public_key=public,nonce=nonce,proof=wrong)
 except ValueError as error:assert str(error)=="device_proof_invalid"
 else:raise AssertionError("wrong proof accepted")
 assert authority.activate(license_id=ent["license_id"],device_public_key=public,nonce=nonce,proof=proof)["schema_version"]==2
