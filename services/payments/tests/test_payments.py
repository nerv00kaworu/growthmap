import base64,hashlib,hmac,json,sqlite3,time
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import pytest
from growthmap_payments.service import Config,PaymentService,BASE_NETWORK,BASE_USDC,SCHEMA_VERSION
from growthmap_payments.api import MockFacilitator,create_app
from growthmap_payments.public_config import APPROVED_BASE_RECIPIENT
from desktop.entitlements import verify_document
RECIPIENT='0x1111111111111111111111111111111111111111';ORIGIN='https://admin.test';CSRF='fixture-csrf';HEAD={'Authorization':'Bearer secret','X-CSRF-Token':CSRF,'Origin':ORIGIN}
MAC_KEY=b'growthmap-isolated-test-settlement-mac-key-v1';AUTHORITY_FIXTURE_KEY=Ed25519PrivateKey.generate();AUTHORITY_FIXTURE_PUBLIC=AUTHORITY_FIXTURE_KEY.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
def config(path,key=None,limit=1000,mac_key=MAC_KEY,checkpoint=None,authority_identity=None):
 identity=authority_identity or {'authority_id':'growthmap-authority-primary','key_id':'isolated-fixture-key','generation':1,'public_key_sha256':hashlib.sha256(AUTHORITY_FIXTURE_PUBLIC).hexdigest(),'attestation':'offline-fixture','public_key':AUTHORITY_FIXTURE_PUBLIC}
 return Config(path,RECIPIENT,hashlib.sha256(b'secret').hexdigest(),key or Ed25519PrivateKey.generate(),ORIGIN,CSRF,'https://payments.test',quote_seconds=60,rate_limit=limit,isolated_test=True,settlement_mac_key=mac_key,settlement_checkpoint_path=checkpoint or path.with_suffix('.checkpoint'),authority_id=identity['authority_id'],authority_key_id=identity['key_id'],authority_generation=identity['generation'],authority_public_key_sha256=identity['public_key_sha256'],authority_attestation=identity['attestation'],authority_public_key=identity['public_key'])
@pytest.fixture
def env(tmp_path):
 c=config(tmp_path/'p.sqlite');return PaymentService(c,MockFacilitator()),c

def sig(challenge,**changes):
 a=challenge['accepts'][0];auth={'from':'0x'+'2'*40,'to':a['payTo'],'value':a['amount'],'validBefore':int(time.time())+60,'nonce':'nonce-'+a['extra']['orderId'],'asset':a['asset'],'orderId':a['extra']['orderId']};auth.update(changes);e={'x402Version':2,'scheme':'exact','network':a['network'],'payload':{'authorization':auth}};return base64.urlsafe_b64encode(json.dumps(e).encode()).decode().rstrip('=')
def seed_confirmed(svc,n):
 for i in range(n):
  o=svc.create_order('paypal',f's{i}@e.test');svc.paypal_submit(o['order_id'],f'TX{i}');svc.paypal_confirm(o['order_id'],f'TX{i}',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})

def test_non_test_config_rejects_missing_or_weak_settlement_mac_key(tmp_path):
 missing=replace(config(tmp_path/'missing.sqlite'),settlement_mac_key=None)
 with pytest.raises(RuntimeError,match='settlement MAC key'):missing.validate()
 weak=replace(config(tmp_path/'weak.sqlite'),settlement_mac_key=b'too-short')
 with pytest.raises(RuntimeError,match='settlement MAC key'):weak.validate()


def test_schema_migration_integrity_append_only_and_unknown_version(tmp_path):
 p=tmp_path/'p.sqlite';s=PaymentService(config(p));
 with s._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION and db.execute('PRAGMA foreign_key_check').fetchall()==[] and db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  s.create_order('paypal','a@e.test')
  with pytest.raises(sqlite3.DatabaseError):db.execute("UPDATE audit_events SET operation='x'")
 PaymentService(config(p))
 with sqlite3.connect(p) as db:db.execute(f'PRAGMA user_version={SCHEMA_VERSION+1}')
 with pytest.raises(RuntimeError):PaymentService(config(p))

def test_two_instances_atomic_quotes_and_49_50_51(tmp_path):
 c=config(tmp_path/'p.sqlite');a=PaymentService(c);b=PaymentService(c);seed_confirmed(a,49)
 with ThreadPoolExecutor(2) as x:orders=list(x.map(lambda pair:pair[0].create_order(pair[1],f'{pair[1]}@e.test'),[(a,'x402'),(b,'paypal')]))
 assert [o['amount_minor'] for o in orders]==[10_000_000,1000] # quote does not reserve
 def confirm(pair):
  svc,o=pair
  if o['currency']=='USD':svc.paypal_submit(o['order_id'],'EDGE');return svc.paypal_confirm(o['order_id'],'EDGE',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})['state']
  return svc.confirm_payment_and_allocate_sale(o['order_id'],'EDGE-X',10_000_000,'USDC')['state']
 with ThreadPoolExecutor(2) as x:states=list(x.map(confirm,[(a,orders[0]),(b,orders[1])]))
 assert sorted(states)==['manual_review','payment_confirmed']
 regular=a.create_order('paypal','r@e.test');assert regular['amount_minor']==2900
 with a._db() as db:assert [r[0] for r in db.execute('SELECT sale_ordinal FROM orders WHERE sale_ordinal>=49 ORDER BY sale_ordinal')]==[49,50]
 assert a.verify_audit() and b.verify_audit()

def test_durable_x402_intent_multi_instance_and_ambiguity(tmp_path):
 c=config(tmp_path/'p.sqlite');a=PaymentService(c);b=PaymentService(c);seed_confirmed(a,49);oa=a.create_order('x402','a@e.test');ob=b.create_order('x402','b@e.test')
 first=a.prepare_x402_intent(oa['order_id'],'proof-a','nonce-a',10_000_000,'0x'+'2'*40);assert first['ordinal']==50
 with pytest.raises(ValueError):b.prepare_x402_intent(ob['order_id'],'proof-b','nonce-b',10_000_000,'0x'+'2'*40)
 a.record_settlement_result(first['intent_id'],'0x'+'3'*64,'evidence-a','mock',PaymentService.now(),payer='0x'+'2'*40,finality_basis='offline_fixture');row=a.finalize_x402_intent(first['intent_id']);assert row['sale_ordinal']==50 and a.finalize_x402_intent(first['intent_id'])['license_id']==row['license_id']
 oc=a.create_order('x402','c@e.test');intent=a.prepare_x402_intent(oc['order_id'],'proof-c','nonce-c',29_000_000,'0x'+'2'*40);a.mark_intent_ambiguous(intent['intent_id'],'timeout')
 with a._db() as db:assert db.execute('SELECT state FROM orders WHERE id=?',(oc['order_id'],)).fetchone()[0]=='manual_review' and db.execute('SELECT state FROM settlement_intents WHERE intent_id=?',(intent['intent_id'],)).fetchone()[0]=='ambiguous'
 expiring=PaymentService(replace(c,intent_seconds=-1));od=expiring.create_order('x402','d@e.test');expired=expiring.prepare_x402_intent(od['order_id'],'proof-d','nonce-d',29_000_000,'0x'+'2'*40)
 PaymentService(c)
 with a._db() as db:assert db.execute('SELECT state FROM settlement_intents WHERE intent_id=?',(expired['intent_id'],)).fetchone()[0]=='ambiguous'

def test_restart_finalizes_recorded_settlement_exactly_once_without_provider(tmp_path):
 c=config(tmp_path/'p.sqlite');s=PaymentService(c);o=s.create_order('x402','restart@e.test');it=s.prepare_x402_intent(o['order_id'],'restart-proof','restart-nonce',10_000_000,'0x'+'2'*40)
 s.record_settlement_result(it['intent_id'],'0x'+'a'*64,'restart-evidence','trusted-finality',PaymentService.now(),payer='0x'+'2'*40,finality_basis='offline_fixture')
 class MustNotCall:
  def verify(self,*a):raise AssertionError('provider verify called')
  def settle(self,*a):raise AssertionError('provider settle called')
 restart=PaymentService(c,MustNotCall())
 with restart._db() as db:
  order=dict(db.execute('SELECT * FROM orders WHERE id=?',(o['order_id'],)).fetchone());assert order['state']=='payment_confirmed' and order['sale_ordinal']==1
  assert db.execute('SELECT count(*) FROM payment_proofs WHERE order_id=?',(o['order_id'],)).fetchone()[0]==1
  assert db.execute("SELECT count(*) FROM audit_events WHERE object_id=? AND operation='entitlement.enqueued'",(o['order_id'],)).fetchone()[0]==1
 license_id=order['license_id'];again=PaymentService(c,MustNotCall())
 with again._db() as db:
  same=dict(db.execute('SELECT * FROM orders WHERE id=?',(o['order_id'],)).fetchone());assert (same['license_id'],same['sale_ordinal'])==(license_id,1)
  assert db.execute('SELECT count(*) FROM payment_proofs WHERE order_id=?',(o['order_id'],)).fetchone()[0]==1

def test_paypal_decimal_claim_binding_duplicates_and_transitions(env):
 s,c=env
 assert s.paypal_minor('10')==1000 and s.paypal_minor('10.00')==1000
 for v in ['10.000001','NaN','Infinity','1e1',10,10.0]:
  with pytest.raises(ValueError):s.paypal_minor(v)
 o=s.create_order('paypal','p@e.test');s.paypal_submit(o['order_id'],'TX-1')
 with pytest.raises(ValueError):s.paypal_confirm(o['order_id'],'OTHER',{'amount':'10','currency':'USD','status':'COMPLETED','payee_verified':True})
 issued=s.paypal_confirm(o['order_id'],'TX-1',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert issued['state']=='payment_confirmed'
 assert s.admin_transition(o['order_id'],'refund')['state']=='refunded' and s.admin_transition(o['order_id'],'refund')['idempotent']
 with pytest.raises(ValueError):s.admin_transition(o['order_id'],'revoke')
 bad=s.create_order('x402','x@e.test')
 with pytest.raises(ValueError):s.paypal_submit(bad['order_id'],'TX-2')
 p=s.create_order('paypal','q@e.test')
 with pytest.raises(ValueError):s.paypal_submit(p['order_id'],'TX-1')

def test_http_all_responses_no_store_and_generic_500(tmp_path):
 c=config(tmp_path/'headers.sqlite');app=create_app(c,MockFacilitator())
 @app.get('/injected-500')
 async def injected():raise RuntimeError('INTERNAL-MARKER-DO-NOT-LEAK')
 client=TestClient(app,raise_server_exceptions=False)
 good=client.post('/v1/orders',json={'rail':'paypal','email':'headers@e.test'});paypal=good.json()
 client.post(f"/v1/orders/{paypal['order_id']}/paypal-submit",json={'transaction_id':'DUP'});conflict=client.post(f"/v1/orders/{paypal['order_id']}/paypal-submit",json={'transaction_id':'DUP'})
 responses=[good,None,client.get('/missing'),conflict,client.post('/v1/orders',json={'rail':'bad','email':'headers@e.test'}),client.get('/injected-500')]
 x=client.post('/v1/orders',json={'rail':'x402','email':'xheaders@e.test'}).json();responses[1]=client.post(f"/v1/orders/{x['order_id']}/purchase")
 assert {r.status_code for r in responses}=={200,402,404,409,422,500}
 assert all(r.headers.get('cache-control')=='no-store' for r in responses)
 assert responses[-1].json()=={'detail':'Internal server error'} and 'INTERNAL-MARKER' not in responses[-1].text

def test_http_challenge_envelope_auth_rate_limit_and_ambiguity(tmp_path):
 c=config(tmp_path/'p.sqlite',limit=10);fac=MockFacilitator();client=TestClient(create_app(c,fac));created=client.post('/v1/orders',json={'rail':'x402','email':'x@e.test'});assert created.headers['cache-control']=='no-store';o=created.json();r=client.post(f"/v1/orders/{o['order_id']}/purchase");challenge=json.loads(base64.b64decode(r.headers['PAYMENT-REQUIRED']))
 assert r.status_code==402 and r.headers['cache-control']=='no-store' and challenge['resource']['mimeType']=='application/json';a=challenge['accepts'][0];assert (a['network'],a['asset'])==(BASE_NETWORK,BASE_USDC)
 malformed=base64.urlsafe_b64encode(json.dumps({'amount':a['amount']}).encode()).decode();assert client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':malformed}).status_code==409
 ok=client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert ok.status_code==202 and ok.json()['state']=='payment_settled_activation_pending' and ok.headers['cache-control']=='no-store'
 replay=client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert replay.status_code in (409,410) and replay.headers['cache-control']=='no-store'
 p_created=client.post('/v1/orders',json={'rail':'paypal','email':'p@e.test'});assert p_created.headers['cache-control']=='no-store';p=p_created.json();submitted=client.post(f"/v1/orders/{p['order_id']}/paypal-submit",json={'transaction_id':'HTTP-TX'});assert submitted.headers['cache-control']=='no-store';assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'Origin':'https://wrong.test'}).headers['cache-control']=='no-store';assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'X-CSRF-Token':'wrong'}).status_code==403;assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'Authorization':'Bearer wrong'}).status_code==403;admin_ok=client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers=HEAD);assert admin_ok.status_code==200 and admin_ok.headers['cache-control']=='no-store'
 assert client.get('/v1/recovery/'+o['recovery_code']).status_code==404

def test_v8_fresh_paypal_cannot_write_portable_license(env):
 s,_=env;o=s.create_order('paypal','z@e.test');s.paypal_submit(o['order_id'],'Z');r=s.paypal_confirm(o['order_id'],'Z',{'amount':'10','currency':'USD','status':'COMPLETED','payee_verified':True});assert r['state']=='payment_confirmed' and r['license_id'] is None and r['license_json'] is None
 with s._db() as db:
  with pytest.raises(sqlite3.IntegrityError,match='portable'):db.execute("UPDATE orders SET license_json='{}' WHERE id=?",(o['order_id'],))


def test_old_v1_upgrade_preserves_and_converts_amounts(tmp_path):
 p=tmp_path/'old.sqlite';sql=(Path(__file__).parents[1]/'migrations/001_payments_v1.sql').read_text()
 with sqlite3.connect(p) as db:
  db.executescript(sql);now=PaymentService.now()
  base=('pending_payment','early',now,'u@e.test','Personal',now,now)
  db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES('x','hx','x402',?,?,?,?,?,?,?,?,?)",(base[0],10_000_000,'USDC',*base[1:]))
  db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES('p','hp','paypal',?,?,?,?,?,?,?,?,?)",(base[0],10_000_000,'USD',*base[1:]))
  db.execute("INSERT INTO payment_proofs VALUES('proof','paypal','p','tx','2026-01-01')")
  db.execute("INSERT INTO external_events VALUES('ev','paypal','p','2026-01-01')")
  db.execute("INSERT INTO audit_events(event_id,at,actor,operation,object_id,data_hash,previous_hash,chain_hash) VALUES('e',?,'old','old','x','d','p','c')",(now,))
 s=PaymentService(config(p))
 with s._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
  assert dict(db.execute('SELECT id,quoted_amount_minor FROM orders').fetchall())=={'x':10_000_000,'p':1000}
  assert tuple(db.execute("SELECT * FROM payment_proofs WHERE proof_hash='proof'").fetchone())==('proof','paypal','p','tx','2026-01-01')
  assert tuple(db.execute("SELECT * FROM external_events WHERE event_hash='ev'").fetchone())==('ev','paypal','p','2026-01-01')
  assert db.execute("SELECT count(*) FROM audit_events WHERE event_id='e'").fetchone()[0]==1
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 PaymentService(config(p))

def test_v2_ledger_fail_closed_and_populated_upgrade_to_v3(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'v2.sqlite';monkeypatch.setattr(module,'SCHEMA_VERSION',2);PaymentService(config(p))
 with sqlite3.connect(p) as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==2
  now=PaymentService.now();db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount_minor,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES('o','h','x402','manual_review',10000000,'USDC','early','2099','u@e.test','P',?,?)",(now,now))
  db.execute("INSERT INTO settlement_intents VALUES('i','o','proof','nonce',10000000,'USDC',1,'2000','ambiguous',NULL,'legacy-evidence','trusted',?, 'admin',?,?)",(now,now,now))
 monkeypatch.setattr(module,'SCHEMA_VERSION',5);s=PaymentService(config(p))
 with s._db() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==5 and db.execute("SELECT state FROM settlement_intents WHERE intent_id='i'").fetchone()[0]=='ambiguous'
 PaymentService(config(p))
 with sqlite3.connect(p) as db:db.execute('DELETE FROM migration_ledger')
 with pytest.raises(RuntimeError,match='ledger'):PaymentService(config(p))

def test_settlement_evidence_replay_and_cross_intent_rejected(tmp_path):
 s=PaymentService(config(tmp_path/'evidence.sqlite'));intents=[]
 for n in range(2):
  o=s.create_order('x402',f'e{n}@e.test');intents.append(s.prepare_x402_intent(o['order_id'],f'proof-{n}',f'nonce-{n}',10_000_000,'0x'+'2'*40))
 final=PaymentService.now();s.record_settlement_result(intents[0]['intent_id'],'0x'+'b'*64,'same-durable-evidence','trusted',final,payer='0x'+'2'*40,finality_basis='offline_fixture')
 with pytest.raises(ValueError,match='already used'):s.record_settlement_result(intents[1]['intent_id'],'0x'+'c'*64,'same-durable-evidence','trusted',final,payer='0x'+'2'*40,finality_basis='offline_fixture')
 with s._db() as db:
  with pytest.raises(sqlite3.DatabaseError,match='immutable'):db.execute("UPDATE settlement_intents SET evidence_binding='0' WHERE intent_id=?",(intents[0]['intent_id'],))
 issued=s.finalize_x402_intent(intents[0]['intent_id'])
 with s._db() as db:
  with pytest.raises(sqlite3.DatabaseError,match='immutable'):db.execute("UPDATE settlement_intents SET evidence_binding='evil' WHERE intent_id=?",(intents[0]['intent_id'],))
 assert issued['state']=='payment_confirmed'

def test_terminal_hmac_tamper_wrong_missing_key_and_immutability(tmp_path):
 p=tmp_path/'trust.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','trust@e.test');it=s.prepare_x402_intent(o['order_id'],'proof','nonce',10_000_000,'0x'+'2'*40);final=s.now();s.record_settlement_result(it['intent_id'],'tx-original','evidence','source',final,payer='0x'+'2'*40,finality_basis='offline_fixture')
 # Simulate a DB attacker by removing the v4 trigger, then recomputing the old public SHA-256 construction.
 with sqlite3.connect(p) as db:
  db.execute('DROP TRIGGER settlement_terminal_immutable');row=db.execute("SELECT * FROM settlement_intents WHERE intent_id=?",(it['intent_id'],)).fetchone();fields={'evidence_hash':'evidence','finality_at':final,'intent_id':it['intent_id'],'nonce_hash':row[3],'order_id':o['order_id'],'outcome':'paid','proof_hash':row[2],'source':'source','tx_hash':'tx-forged'};old=hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':')).encode()).hexdigest();db.execute("UPDATE settlement_intents SET tx_hash=?,evidence_binding=? WHERE intent_id=?",('tx-forged',old,it['intent_id']))
 with pytest.raises(RuntimeError,match='authentication|checkpoint/database mismatch'):PaymentService(c)
 with pytest.raises(RuntimeError,match='missing/weak'):PaymentService(config(tmp_path/'missing.sqlite',mac_key=None))
 # A wrong external trust root must fail before recovering settled evidence.
 with pytest.raises(RuntimeError,match='authentication'):PaymentService(config(p,mac_key=b'x'*32))

def test_admin_failed_auth_throttle_counts_origin_token_csrf_and_rotating_tokens(tmp_path):
 c=config(tmp_path/'auth.sqlite',limit=2);client=TestClient(create_app(c,MockFacilitator()));url='/v1/admin/orders'
 for headers in ({**HEAD,'Origin':'https://wrong.test'},{**HEAD,'X-CSRF-Token':'wrong'}):assert client.get(url,headers=headers).status_code==403
 assert client.get(url,headers={**HEAD,'Authorization':'Bearer third'}).status_code==429
 assert 'secret' not in client.get(url,headers=HEAD).text
 # Separate app proves one fingerprint is also bounded and valid auth works.
 good=TestClient(create_app(config(tmp_path/'auth2.sqlite',limit=2),MockFacilitator()))
 assert good.get(url,headers={'Authorization':'Bearer bad','Origin':ORIGIN,'X-CSRF-Token':CSRF}).status_code==403
 assert good.get(url,headers={'Authorization':'Bearer bad','Origin':ORIGIN,'X-CSRF-Token':CSRF}).status_code==403
 assert good.get(url,headers={'Authorization':'Bearer bad','Origin':ORIGIN,'X-CSRF-Token':CSRF}).status_code==429

class Evidence:
 def __init__(self,outcome,tx=None):self.outcome=outcome;self.tx=tx
 def reconcile(self,i):return {'outcome':self.outcome,'tx_hash':self.tx,'evidence_hash':'ev-'+i['intent_id'],'source':'mock-finality','finality_at':PaymentService.now(),'finality_basis':'offline_fixture_receipt','payer':i['verified_payer'],'proof_hash':i['proof_hash'],'nonce_hash':i['nonce_hash'],'order_id':i['order_id']}

def test_evidence_reconciliation_releases_ambiguity_and_recovers_paid(tmp_path):
 c=config(tmp_path/'p.sqlite');s=PaymentService(c)
 intents=[]
 for i in range(50):
  o=s.create_order('x402',f'a{i}@e.test');it=s.prepare_x402_intent(o['order_id'],f'p{i}',f'n{i}',10_000_000,'0x'+'2'*40);s.mark_intent_ambiguous(it['intent_id'],'timeout');intents.append(it)
 assert s.create_order('paypal','regular@e.test')['amount_minor']==2900
 stale_checkpoint=c.settlement_checkpoint_path.read_bytes()
 with ThreadPoolExecutor(8) as pool:
  results=list(pool.map(lambda it:s.reconcile_intent(it['intent_id'],Evidence('unpaid'),'admin-fixture'),intents))
 assert len(results)==50 and all(r['state']=='cancelled_unpaid' for r in results)
 # An authenticated but stale checkpoint is still a deliberate mismatch, not a
 # concurrency condition to accept. Restore the current document afterward.
 current_checkpoint=c.settlement_checkpoint_path.read_bytes();c.settlement_checkpoint_path.write_bytes(stale_checkpoint)
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):s.create_order('paypal','tamper@e.test')
 c.settlement_checkpoint_path.write_bytes(current_checkpoint)
 # Released ordinals are reusable only after final unpaid evidence.
 assert s.create_order('paypal','early@e.test')['amount_minor']==1000
 o=s.create_order('x402','paid@e.test');it=s.prepare_x402_intent(o['order_id'],'paid-proof','paid-nonce',10_000_000,'0x'+'2'*40)
 s.mark_intent_ambiguous(it['intent_id'],'crash-after-provider-settle');restart=PaymentService(c)
 result=restart.reconcile_intent(it['intent_id'],Evidence('paid','0x'+'4'*64),'admin-fixture')
 assert result['state']=='payment_confirmed' and restart.finalize_x402_intent(it['intent_id'])['license_id']==result['license_id']
 # Cancellation and a competing allocator serialize in SQLite; only one active holder may own an ordinal.
 ox=s.create_order('x402','race-old@e.test');ix=s.prepare_x402_intent(ox['order_id'],'race-old-proof','race-old-nonce',10_000_000,'0x'+'2'*40);s.mark_intent_ambiguous(ix['intent_id'],'race')
 def cancel():return s.reconcile_intent(ix['intent_id'],Evidence('unpaid'),'admin-fixture')
 def allocate():
  for attempt in range(50):
   q=s.create_order('x402',f'race{attempt}@e.test')
   if q['amount_minor']==10_000_000:
    try:return s.prepare_x402_intent(q['order_id'],f'race-proof-{attempt}',f'race-nonce-{attempt}',10_000_000,'0x'+'2'*40)
    except ValueError:pass
   time.sleep(.002)
  raise AssertionError('released ordinal was not allocatable')
 with ThreadPoolExecutor(2) as pool:a,b=pool.submit(cancel),pool.submit(allocate);a.result();new_intent=b.result()
 with s._db() as db:
  active=db.execute("SELECT reserved_ordinal,count(*) FROM settlement_intents WHERE state!='cancelled_unpaid' GROUP BY reserved_ordinal HAVING count(*)>1").fetchall();assert active==[]
  assert db.execute("SELECT state FROM settlement_intents WHERE intent_id=?",(new_intent['intent_id'],)).fetchone()[0]=='prepared'

def test_production_recipient_gate_precedes_other_credentials(tmp_path,monkeypatch):
 import growthmap_payments.api as api
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_ENV','production')
 monkeypatch.delenv('GROWTHMAP_X402_RECIPIENT',raising=False)
 with pytest.raises(RuntimeError,match='recipient missing or not approved'):api.from_env()
 monkeypatch.setenv('GROWTHMAP_X402_RECIPIENT','0x1111111111111111111111111111111111111111')
 with pytest.raises(RuntimeError,match='recipient missing or not approved'):api.from_env()
 monkeypatch.setenv('GROWTHMAP_X402_RECIPIENT',APPROVED_BASE_RECIPIENT)
 with pytest.raises(RuntimeError) as caught:api.from_env()
 assert 'recipient missing or not approved' not in str(caught.value)


def test_public_recipient_config_matches_desktop_truth():
 public=json.loads((Path(__file__).parents[1]/'public-config.json').read_text())
 desktop=json.loads((Path(__file__).parents[3]/'desktop/commercial-config.json').read_text())
 assert public=={'baseNetwork':desktop['baseNetwork'],'basePayee':desktop['basePayee']}
 assert public['basePayee']==APPROVED_BASE_RECIPIENT


def test_env_mock_requires_explicit_opt_in(tmp_path,monkeypatch):
 import growthmap_payments.api as api
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_DB',str(tmp_path/'none.sqlite'));monkeypatch.setenv('GROWTHMAP_X402_RECIPIENT',RECIPIENT);monkeypatch.setenv('GROWTHMAP_PURCHASE_RESOURCE_BASE','https://pay.test');monkeypatch.setenv('GROWTHMAP_ADMIN_ORIGIN',ORIGIN);monkeypatch.setenv('GROWTHMAP_CSRF_SECRET',CSRF);monkeypatch.setenv('GROWTHMAP_ADMIN_SESSION_SHA256',hashlib.sha256(b'secret').hexdigest());monkeypatch.setenv('GROWTHMAP_AUTHORITY_ID','growthmap-authority-primary');monkeypatch.setenv('GROWTHMAP_AUTHORITY_KEY_ID','isolated-fixture-key');monkeypatch.setenv('GROWTHMAP_AUTHORITY_GENERATION','1');authority_public=tmp_path/'authority-public.pem';authority_public.write_bytes(AUTHORITY_FIXTURE_PUBLIC);monkeypatch.setenv('GROWTHMAP_AUTHORITY_PUBLIC_KEY_FILE',str(authority_public));monkeypatch.setenv('GROWTHMAP_AUTHORITY_PUBLIC_KEY_SHA256',hashlib.sha256(AUTHORITY_FIXTURE_PUBLIC).hexdigest());monkeypatch.setenv('GROWTHMAP_AUTHORITY_ATTESTATION','offline-fixture');mac=tmp_path/'mac.key';mac.write_bytes(MAC_KEY);monkeypatch.setenv('GROWTHMAP_SETTLEMENT_MAC_KEY_FILE',str(mac));monkeypatch.setenv('GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE',str(tmp_path/'terminal.checkpoint'))
 app=api.from_env();assert app.state.payments.facilitator is None
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_TEST_MODE','1');monkeypatch.setenv('GROWTHMAP_PAYMENTS_DB',str(tmp_path/'mock.sqlite'));app=api.from_env();assert isinstance(app.state.payments.facilitator,MockFacilitator)
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_ENV','production')
 with pytest.raises(RuntimeError):api.from_env()

def test_failed_v2_migration_rolls_back_coherent_v1(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'rollback.sqlite';root=tmp_path/'migrations';root.mkdir();v1=(Path(__file__).parents[1]/'migrations/001_payments_v1.sql').read_text()
 with sqlite3.connect(p) as db:
  db.executescript(v1);db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES('o','h','paypal','pending_payment',10000000,'USD','early','2099-01-01T00:00:00+00:00','u@e.test','P','2026','2026')");db.execute("INSERT INTO payment_proofs VALUES('proof','paypal','o','tx','2026')")
 bad="CREATE TABLE orders_v2(x); INSERT INTO missing_table VALUES(1);";bad_path=Path(module.__file__).parents[1]/'migrations/999_injected_failure.sql';bad_path.write_text(bad)
 try:
  monkeypatch.setattr(module,'MIGRATIONS',{1:module.MIGRATIONS[1],2:(bad_path.name,hashlib.sha256(bad.encode()).hexdigest())});monkeypatch.setattr(module,'SCHEMA_VERSION',2)
  with pytest.raises(sqlite3.DatabaseError):PaymentService(config(p))
 finally:bad_path.unlink()
 with sqlite3.connect(p) as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==1
  assert db.execute("SELECT quoted_amount FROM orders WHERE id='o'").fetchone()[0]==10_000_000
  assert tuple(db.execute("SELECT * FROM payment_proofs").fetchone())==('proof','paypal','o','tx','2026')
  assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='orders_v2'").fetchone()[0]==0
  assert db.execute('PRAGMA foreign_key_check').fetchall()==[] and db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

def test_r5_checkpoint_detects_terminal_deletion_and_all_field_tamper(tmp_path):
 p=tmp_path/'r5.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','r5@e.test');it=s.prepare_x402_intent(o['order_id'],'p','n',10_000_000,'0x'+'2'*40);s.record_settlement_result(it['intent_id'],'tx','ev','trusted',s.now(),payer='0x'+'2'*40,finality_basis='offline_fixture')
 with sqlite3.connect(p) as db:
  db.execute('DROP TRIGGER settlement_terminal_immutable');db.execute('DROP TRIGGER settlement_terminal_delete');db.execute("UPDATE settlement_intents SET amount_minor=1,currency='EVIL',reserved_ordinal=777 WHERE intent_id=?",(it['intent_id'],))
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)
 # Restore DB from a fresh fixture, then prove deletion is independently detected.
 p2=tmp_path/'delete.sqlite';c2=config(p2);s2=PaymentService(c2);o=s2.create_order('x402','d@e.test');it=s2.prepare_x402_intent(o['order_id'],'p2','n2',10_000_000,'0x'+'2'*40);s2.record_settlement_result(it['intent_id'],'tx2','ev2','trusted',s2.now(),payer='0x'+'2'*40,finality_basis='offline_fixture')
 with sqlite3.connect(p2) as db:db.execute('DROP TRIGGER settlement_terminal_delete');db.execute('DELETE FROM settlement_intents WHERE intent_id=?',(it['intent_id'],))
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c2)

def test_failed_admin_auth_does_not_consume_authenticated_action_bucket(tmp_path):
 client=TestClient(create_app(config(tmp_path/'split.sqlite',limit=2),MockFacilitator()));url='/v1/admin/orders'
 assert client.get(url,headers={**HEAD,'Authorization':'Bearer bad-1'}).status_code==403
 assert client.get(url,headers={**HEAD,'Authorization':'Bearer bad-2'}).status_code==403
 assert client.get(url,headers=HEAD).status_code==200
 assert client.get(url,headers=HEAD).status_code==200
 assert client.get(url,headers=HEAD).status_code==429

def test_r5_wrong_or_missing_checkpoint_and_wrong_key_fail_closed(tmp_path):
 p=tmp_path/'cp.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','cp@e.test');it=s.prepare_x402_intent(o['order_id'],'pc','nc',10_000_000,'0x'+'2'*40);s.record_settlement_result(it['intent_id'],'txc','evc','trusted',s.now(),payer='0x'+'2'*40,finality_basis='offline_fixture')
 c.settlement_checkpoint_path.write_text('{"forged":true}')
 with pytest.raises(RuntimeError,match='checkpoint invalid'):PaymentService(c)
 c.settlement_checkpoint_path.unlink()
 with pytest.raises(RuntimeError,match='checkpoint missing'):PaymentService(c)
 with pytest.raises(RuntimeError,match='checkpoint missing|authentication'):PaymentService(config(p,mac_key=b'z'*32))

def test_r6_closure_rejects_order_recovery_license_proof_audit_and_schema_tamper(tmp_path):
 def settled(name):
  p=tmp_path/(name+'.sqlite');c=config(p);s=PaymentService(c);o=s.create_order('x402',name+'@e.test');i=s.prepare_x402_intent(o['order_id'],'proof-'+name,'nonce-'+name,10_000_000,'0x'+'2'*40);s.record_settlement_result(i['intent_id'],'tx-'+name,'ev-'+name,'trusted',s.now(),payer='0x'+'2'*40,finality_basis='offline_fixture');return p,c,s,o,i
 mutations=[
  "UPDATE orders SET recovery_code_hash='attacker'",
  "UPDATE orders SET state='license_issued',license_id='fake',sale_ordinal=44,tx_hash='fake'",
  "DELETE FROM orders",
  "INSERT INTO audit_events(event_id,at,actor,operation,object_id,data_hash,previous_hash,chain_hash) VALUES('evil','x','x','x','x','x','x','x')",
  "DROP TRIGGER settlement_terminal_delete",
  "DROP INDEX active_intent_ordinal",
 ]
 for n,sql in enumerate(mutations):
  p,c,s,o,i=settled(str(n))
  with sqlite3.connect(p) as db:
   db.execute('PRAGMA foreign_keys=OFF');db.execute(sql)
  with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)
 p,c,s,o,i=settled('proof')
 with sqlite3.connect(p) as db:db.execute("UPDATE settlement_intents SET state='finalized_paid'");db.execute("INSERT INTO payment_proofs VALUES('evil','x402',?,'evil','x')",(o['order_id'],))
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)

def test_r6_paypal_closure_and_normal_flow(tmp_path):
 p=tmp_path/'paypal.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('paypal','p@e.test');s.paypal_submit(o['order_id'],'paypal-tx');row=s.paypal_confirm(o['order_id'],'paypal-tx',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert row['state']=='payment_confirmed'
 PaymentService(c)
 with sqlite3.connect(p) as db:db.execute("UPDATE orders SET recovery_code_hash='attacker'")
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)

def _populate_legacy_terminal(service, *, intent_id='legacy-intent', order_id='legacy-order'):
 now=service.now()
 with service._db() as db:
  db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount_minor,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(order_id,'legacy-recovery-'+order_id,'x402','pending_payment',10_000_000,'USDC','early','2099-01-01T00:00:00+00:00','legacy@e.test','Personal',now,now))
  values={'intent_id':intent_id,'order_id':order_id,'proof_hash':'legacy-proof-'+intent_id,'nonce_hash':'legacy-nonce-'+intent_id,'amount_minor':10_000_000,'currency':'USDC','reserved_ordinal':1,'lease_expires_at':'2099-01-01T00:00:00+00:00','state':'settled','tx_hash':'legacy-tx-'+intent_id,'evidence_hash':'legacy-evidence-'+intent_id,'evidence_source':'trusted-fixture','finality_at':now,'reconciled_by':'fixture','created_at':now,'updated_at':now,'evidence_binding':None}
  values['evidence_binding']=service._evidence_binding(values,values['tx_hash'],values['evidence_hash'],values['evidence_source'],values['finality_at'])
  cols=','.join(values);db.execute(f"INSERT INTO settlement_intents({cols}) VALUES({','.join('?' for _ in values)})",tuple(values.values()))
 return values

def _write_v5_checkpoint(service):
 with service._db() as db:
  rows=[dict(r) for r in db.execute("SELECT * FROM settlement_intents WHERE state IN('settled','finalized_paid','cancelled_unpaid') ORDER BY intent_id")]
  seq=db.execute("SELECT sequence FROM terminal_checkpoint_state WHERE singleton=1").fetchone()[0]
 core={'count':len(rows),'root':hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'sequence':seq,'version':1}
 raw=json.dumps(core,sort_keys=True,separators=(',',':')).encode();core['mac']=hmac.new(service.config.settlement_mac_key,b'growthmap-terminal-checkpoint-v1\0'+raw,hashlib.sha256).hexdigest();service.config.settlement_checkpoint_path.write_text(json.dumps(core,sort_keys=True,separators=(',',':'))+'\n')

def _assert_v6_quarantine(service,module):
 with service._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==6
  assert [tuple(r) for r in db.execute('SELECT version,filename,checksum FROM migration_ledger ORDER BY version')]==[(v,*module.MIGRATIONS[v]) for v in range(1,7)]
  assert tuple(db.execute("SELECT state,license_id,license_json,sale_ordinal FROM orders WHERE id='legacy-order'").fetchone())==('manual_review',None,None,None)
  assert tuple(db.execute("SELECT state,evidence_binding FROM settlement_intents WHERE intent_id='legacy-intent'").fetchone())==('ambiguous',None)
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_real_populated_schema_v4_terminal_upgrades_to_v6_quarantine(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'real-v4.sqlite';c=config(p);monkeypatch.setattr(module,'SCHEMA_VERSION',4);legacy=PaymentService(c);_populate_legacy_terminal(legacy)
 with legacy._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==4
  assert [r[0] for r in db.execute('SELECT version FROM migration_ledger ORDER BY version')]==[1,2,3,4]
 monkeypatch.setattr(module,'SCHEMA_VERSION',6);upgraded=PaymentService(c);_assert_v6_quarantine(upgraded,module)
 reopened=PaymentService(c);_assert_v6_quarantine(reopened,module)

def test_real_populated_schema_v5_checkpoint_upgrades_to_v6_quarantine(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'real-v5.sqlite';c=config(p);monkeypatch.setattr(module,'SCHEMA_VERSION',5);legacy=PaymentService(c);_populate_legacy_terminal(legacy);_write_v5_checkpoint(legacy)
 with legacy._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==5
  assert [r[0] for r in db.execute('SELECT version FROM migration_ledger ORDER BY version')]==[1,2,3,4,5]
 monkeypatch.setattr(module,'SCHEMA_VERSION',6);upgraded=PaymentService(c);_assert_v6_quarantine(upgraded,module)
 reopened=PaymentService(c);_assert_v6_quarantine(reopened,module)

def test_v8_locked_trust_finalize_detects_post_commit_tamper(tmp_path):
 c=config(tmp_path/'race.sqlite');s=PaymentService(c);o=s.create_order('x402','race@e.test');i=s.prepare_x402_intent(o['order_id'],'race-proof','race-nonce',10_000_000,'0x'+'2'*40);s.record_settlement_result(i['intent_id'],'race-tx','race-evidence','trusted',s.now(),payer='0x'+'2'*40,finality_basis='offline_fixture');assert s.finalize_x402_intent(i['intent_id'])['state']=='payment_confirmed'
 with sqlite3.connect(c.db_path) as db:db.execute("UPDATE orders SET recovery_code_hash='attacker' WHERE id=?",(o['order_id'],))
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)


def test_r7_sixty_way_mixed_rail_multi_instance_allocation(tmp_path):
 p=tmp_path/'sixty.sqlite';c=config(p);services=[PaymentService(c) for _ in range(8)]
 orders=[services[n%8].create_order('x402' if n%2==0 else 'paypal',f'sixty-{n}@e.test') for n in range(60)]
 def complete(n):
  s=services[n%8];o=orders[n]
  if n%2==0:
   try:
    i=s.prepare_x402_intent(o['order_id'],f'proof-{n}',f'nonce-{n}',10_000_000,'0x'+'2'*40);s.record_settlement_result(i['intent_id'],f'x402-tx-{n}',f'evidence-{n}','fixture',s.now(),payer='0x'+'2'*40,finality_basis='offline_fixture');return s.finalize_x402_intent(i['intent_id'])['state']
   except ValueError:return 'manual_review'
  s.paypal_submit(o['order_id'],f'paypal-tx-{n}');return s.paypal_confirm(o['order_id'],f'paypal-tx-{n}',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})['state']
 with ThreadPoolExecutor(max_workers=60) as pool:states=list(pool.map(complete,range(60)))
 assert states.count('payment_confirmed')==50 and states.count('manual_review')==10
 with services[0]._db() as db:
  rows=db.execute('SELECT state,sale_ordinal,license_id FROM orders').fetchall();ordinals=[r['sale_ordinal'] for r in rows if r['sale_ordinal'] is not None];licenses=[r['license_id'] for r in rows if r['license_id']]
  assert sorted(ordinals)==list(range(1,51));assert licenses==[];assert db.execute("SELECT count(*) FROM entitlement_outbox").fetchone()[0]==db.execute("SELECT count(*) FROM orders WHERE rail='x402' AND state='payment_confirmed'").fetchone()[0]
  assert tuple(db.execute('SELECT count(*),count(DISTINCT proof_hash),count(DISTINCT tx_hash) FROM payment_proofs').fetchone())==(50,50,50)
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 assert services[0].verify_audit();PaymentService(c)

def test_v8_authority_revocation_is_idempotent_and_blocks_activation(tmp_path):
 from licensing.authority import LicenseAuthority
 from test_device_activation_closure import setup,paid,device
 s,a,_=setup(tmp_path);o=paid(s);e=s.deliver_entitlement(o['order_id'],a)
 with s._db() as db:r=dict(db.execute('select * from entitlement_outbox').fetchone())
 digest=s._outbox_payload_digest(r);args=dict(source=r['source'],source_id=r['source_id'],payload_digest=digest,authority_id=s.config.authority_id,signer_identity=a.handshake(),license_id=e['license_id'],action='revoke',reason='administrative',payment_proof=r['proof_hash'],tx_hash=r['tx_hash'],created_at=r['created_at']);assert a.revoke_external_entitlement(**args);assert a.revoke_external_entitlement(**args)
 public,nonce,proof=device(e['license_id'])
 with pytest.raises(ValueError,match='unavailable|revoked'):a.issue_activation_challenge(license_id=e['license_id'],device_public_key=public)


def test_v8_revocation_wrong_authority_and_payload_fail_closed(tmp_path):
 from test_device_activation_closure import setup,paid
 s,a,_=setup(tmp_path);o=paid(s);s.deliver_entitlement(o['order_id'],a)
 with s._db() as db:r=dict(db.execute('select * from entitlement_outbox').fetchone())
 with pytest.raises(ValueError,match='wrong_authority'):a.revoke_external_entitlement(source=r['source'],source_id=r['source_id'],payload_digest=s._outbox_payload_digest(r),authority_id='other-authority',signer_identity=a.handshake())
 with pytest.raises(ValueError,match='unavailable'):a.revoke_external_entitlement(source=r['source'],source_id=r['source_id'],payload_digest='0'*64,authority_id=s.config.authority_id,signer_identity=a.handshake(),license_id=r['license_id'] or 'gm_missing',action='revoke',reason='administrative',payment_proof=r['proof_hash'],tx_hash=r['tx_hash'],created_at=r['created_at'])


def test_v8_challenge_replaces_portable_check_in(tmp_path):
 from test_device_activation_closure import setup,paid,device
 s,a,_=setup(tmp_path);o=paid(s);e=s.deliver_entitlement(o['order_id'],a);public,_,_=device(e['license_id']);challenge=a.issue_activation_challenge(license_id=e['license_id'],device_public_key=public);assert challenge['nonce'] and challenge['challenge_id']


def test_populated_v7_upgrades_to_v8_and_legacy_is_read_only(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'v7.sqlite';c=config(p);monkeypatch.setattr(module,'SCHEMA_VERSION',7);PaymentService(c);monkeypatch.setattr(module,'SCHEMA_VERSION',8);v8=PaymentService(c)
 with v8._db() as db:assert db.execute('pragma user_version').fetchone()[0]==8
 PaymentService(c)


def test_migration8_outbox_delete_and_payload_tamper_are_blocked(tmp_path):
 from test_device_activation_closure import setup,paid
 s,a,_=setup(tmp_path);o=paid(s)
 with s._db() as db:
  with pytest.raises(sqlite3.IntegrityError,match='append-only'):db.execute('delete from entitlement_outbox')
  with pytest.raises(sqlite3.IntegrityError,match='immutable'):db.execute("update entitlement_outbox set payer='0x0000000000000000000000000000000000000000'")

def test_public_config_loader_fail_closed_tmp_fixtures(tmp_path):
 import hashlib,os
 from growthmap_payments.public_config import load_public_config
 good=b'{"baseNetwork":"eip155:8453","basePayee":"0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591"}'
 def attempt(raw=good,mode=0o600):
  p=tmp_path/f'c-{len(list(tmp_path.iterdir()))}.json';p.write_bytes(raw);p.chmod(mode);return load_public_config(p,expected_digest=hashlib.sha256(raw).hexdigest())
 assert attempt()['baseNetwork']=='eip155:8453'
 for raw in (b'{"baseNetwork":"x","baseNetwork":"eip155:8453","basePayee":"0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591"}',b'{"baseNetwork":"eip155:8453","BASENETWORK":"eip155:8453","basePayee":"0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591"}',b'\xff'):
  with pytest.raises(RuntimeError):attempt(raw)
 with pytest.raises(RuntimeError):attempt(good,0o622)
 target=tmp_path/'target';target.write_bytes(good);link=tmp_path/'link';link.symlink_to(target)
 with pytest.raises(RuntimeError):load_public_config(link,expected_digest=hashlib.sha256(good).hexdigest())
 fifo=tmp_path/'fifo';os.mkfifo(fifo)
 with pytest.raises(RuntimeError):load_public_config(fifo,expected_digest=hashlib.sha256(good).hexdigest())
 huge=b'{}'+b' '*5000
 with pytest.raises(RuntimeError):attempt(huge)

def test_public_config_platform_metadata_never_calls_posix_uid_on_windows(monkeypatch):
 import growthmap_payments.public_config as module
 class Opened:
  st_uid=123;st_mode=0o100666
 monkeypatch.setattr(module.os,'name','nt')
 monkeypatch.setattr(module.os,'getuid',lambda:(_ for _ in ()).throw(AssertionError('POSIX uid lookup on Windows')),raising=False)
 module._validate_platform_metadata(Opened())


def test_public_config_platform_metadata_rejects_unknown_platform(monkeypatch):
 import growthmap_payments.public_config as module
 class Opened:
  st_uid=0;st_mode=0o100600
 monkeypatch.setattr(module.os,'name','unsupported')
 with pytest.raises(RuntimeError,match='platform is unsupported'):module._validate_platform_metadata(Opened())


def test_generated_public_config_digest_and_parity():
 import hashlib,subprocess,sys
 root=Path(__file__).parents[3];public=(Path(__file__).parents[1]/'public-config.json').read_bytes()
 from growthmap_payments.public_config import PUBLIC_CONFIG_SHA256
 assert hashlib.sha256(public).hexdigest()==PUBLIC_CONFIG_SHA256
 subprocess.run([sys.executable,str(root/'tools/generate-public-config.py'),'--check'],cwd=root,check=True)

def test_generator_strict_canonical_and_independent_review_pin(tmp_path):
 import importlib.util,subprocess,sys,shutil
 root=Path(__file__).parents[3];spec=importlib.util.spec_from_file_location('public_generator',root/'tools/generate-public-config.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 raw=(root/'config/commercial-public-config.json').read_bytes();doc=json.loads(raw)
 for invalid in (
  raw.replace(b'"schemaVersion": 3',b'"schemaVersion": 3, "schemaVersion": 3'),
  raw.replace(b'"schemaVersion": 3',b'"schemaVersion": 3, "extra": true'),
  raw.replace(b'"schemaVersion": 3',b'"schemaVersion": "3"'),
  raw.replace(b'"baseNetwork": "eip155:8453"',b'"baseNetwork": "wrong"'),
  raw.replace(b'"schemaVersion": 3',('"schemaVersion": 3, "ＳＣＨＥＭＡＶＥＲＳＩＯＮ": 3').encode()),
 ):
  with pytest.raises(ValueError):module.load_and_validate(invalid)
 tree=tmp_path/'candidate';(tree/'tools').mkdir(parents=True);(tree/'config').mkdir();shutil.copy2(root/'tools/generate-public-config.py',tree/'tools/generate-public-config.py');shutil.copy2(root/'config/commercial-public-config.json',tree/'config/commercial-public-config.json');shutil.copy2(root/'config/commercial-public-config.sha256',tree/'config/commercial-public-config.sha256')
 subprocess.run([sys.executable,'tools/generate-public-config.py'],cwd=tree,check=True)
 before={p.relative_to(tree):p.read_bytes() for p in tree.rglob('*') if p.is_file()}
 subprocess.run([sys.executable,'tools/generate-public-config.py'],cwd=tree,check=True);assert before=={p.relative_to(tree):p.read_bytes() for p in tree.rglob('*') if p.is_file()}
 canonical=tree/'config/commercial-public-config.json';canonical.write_bytes(canonical.read_bytes().replace(doc['supportEmail'].encode(),b'attacker@example.net'))
 pin_before=(tree/'config/commercial-public-config.sha256').read_bytes();subprocess.run([sys.executable,'tools/generate-public-config.py'],cwd=tree,check=True);assert (tree/'config/commercial-public-config.sha256').read_bytes()==pin_before
 failed=subprocess.run([sys.executable,'tools/generate-public-config.py','--check'],cwd=tree);assert failed.returncode!=0

def test_direct_config_authoritative_recipient_matrix_and_challenge_paths(tmp_path):
 from growthmap_payments.facilitator import OfficialX402Facilitator
 def production(recipient,**changes):
  return replace(config(tmp_path/(hashlib.sha256((recipient+str(changes)).encode()).hexdigest()+'.sqlite')),recipient=recipient,production=True,admin_secret_hash='$argon2id$fixture',**changes)
 case_variant='0x'+APPROVED_BASE_RECIPIENT[2:].upper()
 for recipient in ('','0x1111111111111111111111111111111111111111',case_variant):
  with pytest.raises(RuntimeError,match='recipient'):production(recipient).validate()
 production(APPROVED_BASE_RECIPIENT).validate()
 with pytest.raises(RuntimeError,match='opt-in forbidden'):production(APPROVED_BASE_RECIPIENT,allow_live_payment_recipient=True).validate()
 for recipient,opt_in,accepted in ((RECIPIENT,False,True),(RECIPIENT,True,True),(APPROVED_BASE_RECIPIENT,False,False),(case_variant,False,False),(APPROVED_BASE_RECIPIENT,True,True),(case_variant,True,True)):
  c=replace(config(tmp_path/f'nonprod-{recipient[-4:]}-{opt_in}-{accepted}.sqlite'),recipient=recipient,allow_live_payment_recipient=opt_in)
  if accepted:c.validate()
  else:
   with pytest.raises(RuntimeError,match='live payment recipient'):c.validate()
 class CustomFacilitator:
  def verify(self,*args):raise AssertionError
  def settle(self,*args):raise AssertionError
 official=OfficialX402Facilitator('https://facilitator.test',client=object(),_allow_test_origin=True)
 for index,facilitator in enumerate((None,MockFacilitator(),official,CustomFacilitator())):
  c=production(APPROVED_BASE_RECIPIENT);c=replace(c,db_path=tmp_path/f'authority-{index}.sqlite',settlement_checkpoint_path=tmp_path/f'authority-{index}.checkpoint')
  service=PaymentService(c,facilitator);order=service.create_order('x402',f'authority-{index}@e.test');assert service.challenge(order['order_id'])['accepts'][0]['payTo']==APPROVED_BASE_RECIPIENT
  with pytest.raises(RuntimeError,match='recipient'):PaymentService(replace(c,db_path=tmp_path/f'bad-{index}.sqlite',settlement_checkpoint_path=tmp_path/f'bad-{index}.checkpoint',recipient=RECIPIENT),facilitator)

def test_nonproduction_live_recipient_requires_explicit_valid_opt_in(tmp_path,monkeypatch):
 import growthmap_payments.api as api
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_ENV','test');monkeypatch.setenv('GROWTHMAP_X402_RECIPIENT',APPROVED_BASE_RECIPIENT)
 with pytest.raises(RuntimeError,match='forbidden outside production'):api.from_env()
 monkeypatch.setenv('GROWTHMAP_ALLOW_LIVE_PAYMENT_RECIPIENT','yes')
 with pytest.raises(RuntimeError,match='invalid live payment'):api.from_env()
 monkeypatch.setenv('GROWTHMAP_ALLOW_LIVE_PAYMENT_RECIPIENT','1')
 with pytest.raises(RuntimeError) as caught:api.from_env()
 assert 'live payment recipient' not in str(caught.value)

@pytest.mark.parametrize('version',[8,9,10])
def test_populated_v8_v9_v10_upgrade_identity_matrix(tmp_path,monkeypatch,version):
 import growthmap_payments.service as module
 p=tmp_path/f'v{version}.sqlite';c=config(p);monkeypatch.setattr(module,'SCHEMA_VERSION',version);legacy=PaymentService(c)
 # Representative rows are created by the historical schema itself; v8 has
 # entitlement only, while v9/v10 additionally have revocation.
 with legacy._db() as db:
  now='2026-08-02T00:00:00+00:00'
  for i,state in enumerate(('pending','leased','delivered')):
   oid=f'00000000-0000-0000-0000-000000000{i+1:03d}';db.execute("INSERT INTO orders(id,recovery_code_hash,rail,state,quoted_amount_minor,currency,tier,quote_expires_at,buyer_email,license_name,created_at,updated_at) VALUES(?,?,'x402','payment_confirmed',10000000,'USDC','early',?,'buyer@test','Buyer',?,?)",(oid,hashlib.sha256(oid.encode()).hexdigest(),now,now,now));db.execute("INSERT INTO entitlement_outbox(order_id,source,source_id,proof_hash,tx_hash,evidence_hash,payer,network,asset,amount_minor,product,major_version,state,license_id,created_at,delivered_at,lease_owner,lease_expires_at,delivery_receipt) VALUES(?,'x402',?,?,?,?,?,'eip155:8453',?,10000000,'growthmap',1,?,?,?,?,?,?,?)",(oid,hashlib.sha256(('s'+oid).encode()).hexdigest(),hashlib.sha256(('p'+oid).encode()).hexdigest(),'0x'+hashlib.sha256(('t'+oid).encode()).hexdigest(),hashlib.sha256(('e'+oid).encode()).hexdigest(),RECIPIENT,module.BASE_USDC,state,'gm_'+'a'*32 if state=='delivered' else None,now,now if state=='delivered' else None,'worker' if state=='leased' else None,now if state=='leased' else None,hashlib.sha256(oid.encode()).hexdigest() if state=='delivered' else None))
  db.commit()
 monkeypatch.setattr(module,'SCHEMA_VERSION',11);upgraded=PaymentService(c)
 with upgraded._db() as db:
  rows=db.execute('select state,authority_identity_status,authority_key_id,authority_ack_signature from entitlement_outbox order by order_id').fetchall();assert [r[0] for r in rows]==['quarantined','quarantined','delivered'];assert all(r[1]=='legacy_identity_unproven' and r[2] is None and r[3] is None for r in rows);assert db.execute('pragma integrity_check').fetchone()[0]=='ok';assert db.execute('pragma foreign_key_check').fetchall()==[]
  with pytest.raises(sqlite3.IntegrityError,match='acknowledgement'):db.execute("update entitlement_outbox set state='delivered' where order_id=?",('00000000-0000-0000-0000-000000000001',))
