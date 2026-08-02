import base64,json
from fastapi.testclient import TestClient
from growthmap_payments.api import MockFacilitator,create_app
from test_payments import config,sig
class RaisingAuthority:
 def handshake(self):return {'authority_id':'growthmap-authority-primary','key_id':'isolated-fixture-key','generation':1,'public_key_sha256':'0'*64,'attestation':'offline-fixture'}
 def create_external_entitlement(self,**kwargs):raise RuntimeError('offline')
def test_paid_delivery_failure_is_202_and_never_resettles(tmp_path):
 fac=MockFacilitator();calls={'settle':0};original=fac.settle
 def settle(*a,**k):calls['settle']+=1;return original(*a,**k)
 fac.settle=settle;cfg=config(tmp_path/'pending.sqlite');client=TestClient(create_app(cfg,fac,authority=RaisingAuthority()));order=client.post('/v1/orders',json={'rail':'x402','email':'pending@example.test'}).json();challenge=json.loads(base64.b64decode(client.post(f"/v1/orders/{order['order_id']}/purchase").headers['PAYMENT-REQUIRED']))
 response=client.post(f"/v1/orders/{order['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert response.status_code==202 and response.json()['state']=='payment_settled_activation_pending';assert calls['settle']==1
 again=client.post(f"/v1/orders/{order['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert again.status_code==410 and calls['settle']==1
 with client.app.state.payments._db() as db:
  assert db.execute('select state from settlement_intents').fetchone()[0]=='finalized_paid';assert db.execute('select state from orders').fetchone()[0]=='payment_confirmed';assert db.execute('select state from entitlement_outbox').fetchone()[0]=='pending'
