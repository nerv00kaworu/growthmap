import base64,json,hashlib,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from growthmap_payments.service import Config,PaymentService,BASE_NETWORK,BASE_USDC
from growthmap_payments.api import create_app,MockFacilitator
from desktop.entitlements import verify_document

RECIPIENT="0x1111111111111111111111111111111111111111"
@pytest.fixture
def env(tmp_path):
 key=Ed25519PrivateKey.generate();svc=PaymentService(Config(tmp_path/'pay.sqlite',RECIPIENT,hashlib.sha256(b'secret').hexdigest(),key,quote_seconds=60),MockFacilitator());return svc,key

def test_exact_challenge_and_expiry(env):
 svc,_=env;o=svc.create_order('x402',' A@EXAMPLE.com ');c=svc.challenge(o['order_id']);a=c['accepts'][0]
 assert c['x402Version']==2 and a=={'scheme':'exact','network':BASE_NETWORK,'asset':BASE_USDC,'amount':'10000000','payTo':RECIPIENT,'maxTimeoutSeconds':60,'extra':{'name':'USD Coin','version':'2','orderId':o['order_id'],'product':'growthmap','majorVersion':1}}
 with svc._db() as db:db.execute("UPDATE orders SET quote_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(o['order_id'],))
 with pytest.raises(ValueError):svc.challenge(o['order_id'])

def test_atomic_50_early_cross_rail_and_signature_compatibility(env,tmp_path):
 svc,key=env;orders=[svc.create_order('x402' if i%2 else 'paypal',f'u{i}@e.test') for i in range(60)]
 def confirm(pair):
  i,o=pair
  # Quotes all begin early; only first 50 may settle. Last ten become review instead of paid regular.
  return svc.confirm_payment_and_allocate_sale(o['order_id'],f'proof-{i}',10_000_000,'USDC' if i%2 else 'USD')['state']
 with ThreadPoolExecutor(max_workers=16) as pool:states=list(pool.map(confirm,enumerate(orders)))
 assert states.count('license_issued')==50 and states.count('manual_review')==10
 with svc._db() as db:
  rows=db.execute("SELECT sale_ordinal,license_json FROM orders WHERE confirmed_at IS NOT NULL ORDER BY sale_ordinal").fetchall()
 assert [r[0] for r in rows]==list(range(1,51))
 pub=tmp_path/'pub.pem';pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 assert verify_document(json.loads(rows[0][1]),pub).mutations_allowed
 assert not verify_document(json.loads(rows[0][1]),pub,current_major=2).mutations_allowed
 assert svc.verify_audit()
 with svc._db() as db:db.execute("UPDATE audit_events SET operation='tampered' WHERE seq=1")
 assert not svc.verify_audit()

def test_duplicate_proof_and_exactly_once(env):
 svc,_=env;a=svc.create_order('paypal','a@e.test');b=svc.create_order('x402','b@e.test')
 first=svc.confirm_payment_and_allocate_sale(a['order_id'],'same',10_000_000,'USD');again=svc.confirm_payment_and_allocate_sale(a['order_id'],'different',10_000_000,'USD')
 assert first['license_id']==again['license_id']
 with pytest.raises(ValueError):svc.confirm_payment_and_allocate_sale(b['order_id'],'same',10_000_000,'USDC')

def _sig(challenge,**changes):
 a=challenge['accepts'][0];doc={'network':a['network'],'asset':a['asset'],'amount':a['amount'],'payTo':a['payTo'],'orderId':a['extra']['orderId'],'nonce':'n1','transaction':'0x'+'2'*64,**changes}
 return base64.urlsafe_b64encode(json.dumps(doc).encode()).decode().rstrip('=')

def test_x402_route_validation_replay_and_paypal_admin(env):
 svc,key=env;fac=MockFacilitator();app=create_app(svc.config,fac);client=TestClient(app);o=client.post('/v1/orders',json={'rail':'x402','email':'x@e.test'}).json();r=client.post(f"/v1/orders/{o['order_id']}/purchase")
 assert r.status_code==402 and 'PAYMENT-REQUIRED' in r.headers
 c=json.loads(base64.b64decode(r.headers['PAYMENT-REQUIRED']))
 for changes in ({'network':'eip155:1'},{'asset':'0x'+'0'*40},{'amount':'1'},{'payTo':'0x'+'2'*40},{'orderId':'bad'}):assert client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':_sig(c,**changes)}).status_code==409
 ok=client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':_sig(c)});assert ok.status_code==200 and ok.json()['license']['device_allowance']==2
 assert client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':_sig(c)}).status_code in (409,410)
 p=client.post('/v1/orders',json={'rail':'paypal','email':'p@e.test'}).json();body={'transaction_id':'PAYPAL-1','attestation':{'amount':10,'currency':'USD','status':'COMPLETED','payee_verified':True}}
 assert client.post(f"/v1/admin/orders/{p['order_id']}/paypal-confirm",json=body).status_code==403
 headers={'Authorization':'Bearer secret','X-CSRF-Token':'test-csrf','Origin':'http://testserver'}
 bad=json.loads(json.dumps(body));bad['attestation']['currency']='EUR';assert client.post(f"/v1/admin/orders/{p['order_id']}/paypal-confirm",json=bad,headers=headers).status_code==409
 assert client.post(f"/v1/admin/orders/{p['order_id']}/paypal-confirm",json=body,headers=headers).status_code==200
