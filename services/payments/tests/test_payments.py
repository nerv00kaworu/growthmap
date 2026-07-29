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
from desktop.entitlements import verify_document
RECIPIENT='0x1111111111111111111111111111111111111111';ORIGIN='https://admin.test';CSRF='fixture-csrf';HEAD={'Authorization':'Bearer secret','X-CSRF-Token':CSRF,'Origin':ORIGIN}
MAC_KEY=b'growthmap-isolated-test-settlement-mac-key-v1'
def config(path,key=None,limit=1000,mac_key=MAC_KEY,checkpoint=None):return Config(path,RECIPIENT,hashlib.sha256(b'secret').hexdigest(),key or Ed25519PrivateKey.generate(),ORIGIN,CSRF,'https://payments.test',quote_seconds=60,rate_limit=limit,isolated_test=True,settlement_mac_key=mac_key,settlement_checkpoint_path=checkpoint or path.with_suffix('.checkpoint'))
@pytest.fixture
def env(tmp_path):
 c=config(tmp_path/'p.sqlite');return PaymentService(c,MockFacilitator()),c

def sig(challenge,**changes):
 a=challenge['accepts'][0];auth={'from':'0x'+'2'*40,'to':a['payTo'],'value':a['amount'],'validBefore':int(time.time())+60,'nonce':'nonce-'+a['extra']['orderId'],'asset':a['asset'],'orderId':a['extra']['orderId']};auth.update(changes);e={'x402Version':2,'scheme':'exact','network':a['network'],'payload':{'authorization':auth}};return base64.urlsafe_b64encode(json.dumps(e).encode()).decode().rstrip('=')
def seed_confirmed(svc,n):
 for i in range(n):
  o=svc.create_order('paypal',f's{i}@e.test');svc.paypal_submit(o['order_id'],f'TX{i}');svc.paypal_confirm(o['order_id'],f'TX{i}',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})

def test_non_test_config_rejects_missing_or_weak_settlement_mac_key(tmp_path):
 missing=Config(tmp_path/'missing.sqlite',RECIPIENT,'',None,purchase_resource_base='https://payments.growthmap.app',settlement_checkpoint_path=tmp_path/'missing.checkpoint')
 with pytest.raises(RuntimeError,match='settlement MAC key'):missing.validate()
 weak=Config(tmp_path/'weak.sqlite',RECIPIENT,'',None,purchase_resource_base='https://payments.growthmap.app',settlement_mac_key=b'too-short',settlement_checkpoint_path=tmp_path/'weak.checkpoint')
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
 assert sorted(states)==['license_issued','manual_review']
 regular=a.create_order('paypal','r@e.test');assert regular['amount_minor']==2900
 with a._db() as db:assert [r[0] for r in db.execute('SELECT sale_ordinal FROM orders WHERE sale_ordinal>=49 ORDER BY sale_ordinal')]==[49,50]
 assert a.verify_audit() and b.verify_audit()

def test_durable_x402_intent_multi_instance_and_ambiguity(tmp_path):
 c=config(tmp_path/'p.sqlite');a=PaymentService(c);b=PaymentService(c);seed_confirmed(a,49);oa=a.create_order('x402','a@e.test');ob=b.create_order('x402','b@e.test')
 first=a.prepare_x402_intent(oa['order_id'],'proof-a','nonce-a',10_000_000);assert first['ordinal']==50
 with pytest.raises(ValueError):b.prepare_x402_intent(ob['order_id'],'proof-b','nonce-b',10_000_000)
 a.record_settlement_result(first['intent_id'],'0x'+'3'*64,'evidence-a','mock',PaymentService.now());row=a.finalize_x402_intent(first['intent_id']);assert row['sale_ordinal']==50 and a.finalize_x402_intent(first['intent_id'])['license_id']==row['license_id']
 oc=a.create_order('x402','c@e.test');intent=a.prepare_x402_intent(oc['order_id'],'proof-c','nonce-c',29_000_000);a.mark_intent_ambiguous(intent['intent_id'],'timeout')
 with a._db() as db:assert db.execute('SELECT state FROM orders WHERE id=?',(oc['order_id'],)).fetchone()[0]=='manual_review' and db.execute('SELECT state FROM settlement_intents WHERE intent_id=?',(intent['intent_id'],)).fetchone()[0]=='ambiguous'
 expiring=PaymentService(replace(c,intent_seconds=-1));od=expiring.create_order('x402','d@e.test');expired=expiring.prepare_x402_intent(od['order_id'],'proof-d','nonce-d',29_000_000)
 PaymentService(c)
 with a._db() as db:assert db.execute('SELECT state FROM settlement_intents WHERE intent_id=?',(expired['intent_id'],)).fetchone()[0]=='ambiguous'

def test_restart_finalizes_recorded_settlement_exactly_once_without_provider(tmp_path):
 c=config(tmp_path/'p.sqlite');s=PaymentService(c);o=s.create_order('x402','restart@e.test');it=s.prepare_x402_intent(o['order_id'],'restart-proof','restart-nonce',10_000_000)
 s.record_settlement_result(it['intent_id'],'0x'+'a'*64,'restart-evidence','trusted-finality',PaymentService.now())
 class MustNotCall:
  def verify(self,*a):raise AssertionError('provider verify called')
  def settle(self,*a):raise AssertionError('provider settle called')
 restart=PaymentService(c,MustNotCall())
 with restart._db() as db:
  order=dict(db.execute('SELECT * FROM orders WHERE id=?',(o['order_id'],)).fetchone());assert order['state']=='license_issued' and order['sale_ordinal']==1
  assert db.execute('SELECT count(*) FROM payment_proofs WHERE order_id=?',(o['order_id'],)).fetchone()[0]==1
  assert db.execute("SELECT count(*) FROM audit_events WHERE object_id=? AND operation='license.issued'",(o['order_id'],)).fetchone()[0]==1
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
 issued=s.paypal_confirm(o['order_id'],'TX-1',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert issued['state']=='license_issued'
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
 ok=client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert ok.status_code==200 and ok.headers['cache-control']=='no-store'
 replay=client.post(f"/v1/orders/{o['order_id']}/purchase",headers={'PAYMENT-SIGNATURE':sig(challenge)});assert replay.status_code in (409,410) and replay.headers['cache-control']=='no-store'
 p_created=client.post('/v1/orders',json={'rail':'paypal','email':'p@e.test'});assert p_created.headers['cache-control']=='no-store';p=p_created.json();submitted=client.post(f"/v1/orders/{p['order_id']}/paypal-submit",json={'transaction_id':'HTTP-TX'});assert submitted.headers['cache-control']=='no-store';assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'Origin':'https://wrong.test'}).headers['cache-control']=='no-store';assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'X-CSRF-Token':'wrong'}).status_code==403;assert client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers={**HEAD,'Authorization':'Bearer wrong'}).status_code==403;admin_ok=client.post(f"/v1/admin/orders/{p['order_id']}/reject",headers=HEAD);assert admin_ok.status_code==200 and admin_ok.headers['cache-control']=='no-store'
 code=o['recovery_code'];assert client.get('/v1/recovery/'+code).headers['cache-control']=='no-store';assert client.get('/v1/recovery/'+code).status_code==200

def test_license_compatibility(env,tmp_path):
 s,c=env;o=s.create_order('paypal','z@e.test');s.paypal_submit(o['order_id'],'Z');r=s.paypal_confirm(o['order_id'],'Z',{'amount':'10','currency':'USD','status':'COMPLETED','payee_verified':True});pub=tmp_path/'pub.pem';pub.write_bytes(c.signing_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo));assert verify_document(json.loads(r['license_json']),pub).mutations_allowed

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
  o=s.create_order('x402',f'e{n}@e.test');intents.append(s.prepare_x402_intent(o['order_id'],f'proof-{n}',f'nonce-{n}',10_000_000))
 final=PaymentService.now();s.record_settlement_result(intents[0]['intent_id'],'0x'+'b'*64,'same-durable-evidence','trusted',final)
 with pytest.raises(ValueError,match='already used'):s.record_settlement_result(intents[1]['intent_id'],'0x'+'c'*64,'same-durable-evidence','trusted',final)
 with s._db() as db:
  with pytest.raises(sqlite3.DatabaseError,match='immutable'):db.execute("UPDATE settlement_intents SET evidence_binding='0' WHERE intent_id=?",(intents[0]['intent_id'],))
 issued=s.finalize_x402_intent(intents[0]['intent_id'])
 with s._db() as db:
  with pytest.raises(sqlite3.DatabaseError,match='immutable'):db.execute("UPDATE settlement_intents SET evidence_binding='evil' WHERE intent_id=?",(intents[0]['intent_id'],))
 assert issued['state']=='license_issued'

def test_terminal_hmac_tamper_wrong_missing_key_and_immutability(tmp_path):
 p=tmp_path/'trust.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','trust@e.test');it=s.prepare_x402_intent(o['order_id'],'proof','nonce',10_000_000);final=s.now();s.record_settlement_result(it['intent_id'],'tx-original','evidence','source',final)
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
 def reconcile(self,i):return {'outcome':self.outcome,'tx_hash':self.tx,'evidence_hash':'ev-'+i['intent_id'],'source':'mock-finality','finality_at':PaymentService.now(),'proof_hash':i['proof_hash'],'nonce_hash':i['nonce_hash'],'order_id':i['order_id']}

def test_evidence_reconciliation_releases_ambiguity_and_recovers_paid(tmp_path):
 c=config(tmp_path/'p.sqlite');s=PaymentService(c)
 intents=[]
 for i in range(50):
  o=s.create_order('x402',f'a{i}@e.test');it=s.prepare_x402_intent(o['order_id'],f'p{i}',f'n{i}',10_000_000);s.mark_intent_ambiguous(it['intent_id'],'timeout');intents.append(it)
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
 o=s.create_order('x402','paid@e.test');it=s.prepare_x402_intent(o['order_id'],'paid-proof','paid-nonce',10_000_000)
 s.mark_intent_ambiguous(it['intent_id'],'crash-after-provider-settle');restart=PaymentService(c)
 result=restart.reconcile_intent(it['intent_id'],Evidence('paid','0x'+'4'*64),'admin-fixture')
 assert result['state']=='license_issued' and restart.finalize_x402_intent(it['intent_id'])['license_id']==result['license_id']
 # Cancellation and a competing allocator serialize in SQLite; only one active holder may own an ordinal.
 ox=s.create_order('x402','race-old@e.test');ix=s.prepare_x402_intent(ox['order_id'],'race-old-proof','race-old-nonce',10_000_000);s.mark_intent_ambiguous(ix['intent_id'],'race')
 def cancel():return s.reconcile_intent(ix['intent_id'],Evidence('unpaid'),'admin-fixture')
 def allocate():
  for attempt in range(50):
   q=s.create_order('x402',f'race{attempt}@e.test')
   if q['amount_minor']==10_000_000:
    try:return s.prepare_x402_intent(q['order_id'],f'race-proof-{attempt}',f'race-nonce-{attempt}',10_000_000)
    except ValueError:pass
   time.sleep(.002)
  raise AssertionError('released ordinal was not allocatable')
 with ThreadPoolExecutor(2) as pool:a,b=pool.submit(cancel),pool.submit(allocate);a.result();new_intent=b.result()
 with s._db() as db:
  active=db.execute("SELECT reserved_ordinal,count(*) FROM settlement_intents WHERE state!='cancelled_unpaid' GROUP BY reserved_ordinal HAVING count(*)>1").fetchall();assert active==[]
  assert db.execute("SELECT state FROM settlement_intents WHERE intent_id=?",(new_intent['intent_id'],)).fetchone()[0]=='prepared'

def test_env_mock_requires_explicit_opt_in(tmp_path,monkeypatch):
 import growthmap_payments.api as api
 monkeypatch.setenv('GROWTHMAP_PAYMENTS_DB',str(tmp_path/'none.sqlite'));monkeypatch.setenv('GROWTHMAP_X402_RECIPIENT',RECIPIENT);monkeypatch.setenv('GROWTHMAP_PURCHASE_RESOURCE_BASE','https://pay.test');monkeypatch.setenv('GROWTHMAP_ADMIN_ORIGIN',ORIGIN);monkeypatch.setenv('GROWTHMAP_CSRF_SECRET',CSRF);monkeypatch.setenv('GROWTHMAP_ADMIN_SESSION_SHA256',hashlib.sha256(b'secret').hexdigest());mac=tmp_path/'mac.key';mac.write_bytes(MAC_KEY);monkeypatch.setenv('GROWTHMAP_SETTLEMENT_MAC_KEY_FILE',str(mac));monkeypatch.setenv('GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE',str(tmp_path/'terminal.checkpoint'))
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
 p=tmp_path/'r5.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','r5@e.test');it=s.prepare_x402_intent(o['order_id'],'p','n',10_000_000);s.record_settlement_result(it['intent_id'],'tx','ev','trusted',s.now())
 with sqlite3.connect(p) as db:
  db.execute('DROP TRIGGER settlement_terminal_immutable');db.execute('DROP TRIGGER settlement_terminal_delete');db.execute("UPDATE settlement_intents SET amount_minor=1,currency='EVIL',reserved_ordinal=777 WHERE intent_id=?",(it['intent_id'],))
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)
 # Restore DB from a fresh fixture, then prove deletion is independently detected.
 p2=tmp_path/'delete.sqlite';c2=config(p2);s2=PaymentService(c2);o=s2.create_order('x402','d@e.test');it=s2.prepare_x402_intent(o['order_id'],'p2','n2',10_000_000);s2.record_settlement_result(it['intent_id'],'tx2','ev2','trusted',s2.now())
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
 p=tmp_path/'cp.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','cp@e.test');it=s.prepare_x402_intent(o['order_id'],'pc','nc',10_000_000);s.record_settlement_result(it['intent_id'],'txc','evc','trusted',s.now())
 c.settlement_checkpoint_path.write_text('{"forged":true}')
 with pytest.raises(RuntimeError,match='checkpoint invalid'):PaymentService(c)
 c.settlement_checkpoint_path.unlink()
 with pytest.raises(RuntimeError,match='checkpoint missing'):PaymentService(c)
 with pytest.raises(RuntimeError,match='checkpoint missing|authentication'):PaymentService(config(p,mac_key=b'z'*32))

def test_r6_closure_rejects_order_recovery_license_proof_audit_and_schema_tamper(tmp_path):
 def settled(name):
  p=tmp_path/(name+'.sqlite');c=config(p);s=PaymentService(c);o=s.create_order('x402',name+'@e.test');i=s.prepare_x402_intent(o['order_id'],'proof-'+name,'nonce-'+name,10_000_000);s.record_settlement_result(i['intent_id'],'tx-'+name,'ev-'+name,'trusted',s.now());return p,c,s,o,i
 mutations=[
  "UPDATE orders SET recovery_code_hash='attacker'",
  "UPDATE orders SET state='license_issued',license_id='fake',license_json='{}',sale_ordinal=44,tx_hash='fake'",
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
 p=tmp_path/'paypal.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('paypal','p@e.test');s.paypal_submit(o['order_id'],'paypal-tx');row=s.paypal_confirm(o['order_id'],'paypal-tx',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert row['state']=='license_issued'
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

def test_r7_locked_trust_blocks_finalize_and_recovery_toctou(tmp_path,monkeypatch):
 import threading
 def attacker_after_verified(service,attack,operation):
  verified=threading.Event();attempting=threading.Event();done=threading.Event();original=service._assert_terminal_trust
  def hooked(db=None):
   original(db);verified.set();assert attempting.wait(2)
  monkeypatch.setattr(service,'_assert_terminal_trust',hooked)
  def attacker():
   assert verified.wait(2);attempting.set()
   with sqlite3.connect(service.config.db_path,timeout=10) as db:attack(db)
   done.set()
  thread=threading.Thread(target=attacker);thread.start();result=operation();assert not done.is_set();thread.join(10);assert done.is_set();return result
 p=tmp_path/'finalize-race.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('x402','race@e.test');i=s.prepare_x402_intent(o['order_id'],'race-proof','race-nonce',10_000_000);s.record_settlement_result(i['intent_id'],'race-tx','race-evidence','trusted',s.now())
 issued=attacker_after_verified(s,lambda db:db.execute("UPDATE orders SET recovery_code_hash='attacker' WHERE id=?",(o['order_id'],)),lambda:s.finalize_x402_intent(i['intent_id']))
 assert issued['state']=='license_issued' and issued['recovery_code_hash']!= 'attacker'
 with pytest.raises(RuntimeError,match='^external issuance checkpoint/database mismatch$'):PaymentService(c)
 p2=tmp_path/'recovery-race.sqlite';c2=config(p2);s2=PaymentService(c2);o2=s2.create_order('paypal','recovery-race@e.test');s2.paypal_submit(o2['order_id'],'race-paypal');s2.paypal_confirm(o2['order_id'],'race-paypal',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})
 recovered=attacker_after_verified(s2,lambda db:db.execute("UPDATE orders SET license_json='{}' WHERE id=?",(o2['order_id'],)),lambda:s2.recovery_lookup(o2['recovery_code']))
 assert recovered['state']=='license_issued' and recovered['license']['license_id']
 with pytest.raises(RuntimeError,match='^external issuance checkpoint/database mismatch$'):s2.recovery_lookup(o2['recovery_code'])

def test_r7_sixty_way_mixed_rail_multi_instance_allocation(tmp_path):
 p=tmp_path/'sixty.sqlite';c=config(p);services=[PaymentService(c) for _ in range(8)]
 orders=[services[n%8].create_order('x402' if n%2==0 else 'paypal',f'sixty-{n}@e.test') for n in range(60)]
 def complete(n):
  s=services[n%8];o=orders[n]
  if n%2==0:
   try:
    i=s.prepare_x402_intent(o['order_id'],f'proof-{n}',f'nonce-{n}',10_000_000);s.record_settlement_result(i['intent_id'],f'x402-tx-{n}',f'evidence-{n}','fixture',s.now());return s.finalize_x402_intent(i['intent_id'])['state']
   except ValueError:return 'manual_review'
  s.paypal_submit(o['order_id'],f'paypal-tx-{n}');return s.paypal_confirm(o['order_id'],f'paypal-tx-{n}',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})['state']
 with ThreadPoolExecutor(max_workers=60) as pool:states=list(pool.map(complete,range(60)))
 assert states.count('license_issued')==50 and states.count('manual_review')==10
 with services[0]._db() as db:
  rows=db.execute('SELECT state,sale_ordinal,license_id FROM orders').fetchall();ordinals=[r['sale_ordinal'] for r in rows if r['sale_ordinal'] is not None];licenses=[r['license_id'] for r in rows if r['license_id']]
  assert sorted(ordinals)==list(range(1,51));assert len(licenses)==len(set(licenses))==50
  assert tuple(db.execute('SELECT count(*),count(DISTINCT proof_hash),count(DISTINCT tx_hash) FROM payment_proofs').fetchone())==(50,50,50)
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 assert services[0].verify_audit();PaymentService(c)

def test_signed_revocation_idempotent_recovery_and_checkpoint(tmp_path):
 p=tmp_path/'revoked.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('paypal','revoked@e.test');s.paypal_submit(o['order_id'],'REVOKE-TX');issued=s.paypal_confirm(o['order_id'],'REVOKE-TX',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert s.recovery_lookup(o['recovery_code'])['license']['license_id']==issued['license_id']
 first=s.admin_transition(o['order_id'],'revoke','fraud');again=s.admin_transition(o['order_id'],'revoke','administrative');assert first['revocation']==again['revocation'] and again['idempotent'];assert first['revocation']['reason_code']=='fraud'
 recovered=s.recovery_lookup(o['recovery_code']);assert recovered['state']=='revoked' and recovered['license'] is None and recovered['revocation']==first['revocation']
 PaymentService(c)
 with sqlite3.connect(p) as db:db.execute("DROP TRIGGER revocation_assertion_no_update");db.execute("UPDATE revocation_assertions SET reason_code='refund'")
 with pytest.raises(RuntimeError,match="checkpoint/database mismatch"):PaymentService(c)

def test_revocation_signature_domain_and_validation(env,tmp_path):
 from desktop.entitlements import verify_revocation_assertion
 s,c=env;o=s.create_order('paypal','assertion@e.test');s.paypal_submit(o['order_id'],'ASSERT-TX');issued=s.paypal_confirm(o['order_id'],'ASSERT-TX',{'amount':'10','currency':'USD','status':'COMPLETED','payee_verified':True});a=s.admin_transition(o['order_id'],'revoke')['revocation'];pub=tmp_path/'pub.pem';pub.write_bytes(c.signing_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo));assert verify_revocation_assertion(a,issued['license_id'],pub)['sequence']==1
 for field,value in [('license_id','other'),('major_version',2),('schema_version',2),('reason_code','anything')]:
  bad=dict(a);bad[field]=value
  with pytest.raises(Exception):verify_revocation_assertion(bad,issued['license_id'],pub)
 with pytest.raises(Exception):verify_revocation_assertion(a,issued['license_id'],pub,minimum_sequence=1)
 wrong=tmp_path/'wrong.pem';wrong.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 with pytest.raises(Exception):verify_revocation_assertion(a,issued['license_id'],wrong)
 license_doc=json.loads(issued['license_json'])
 with pytest.raises(Exception):c.signing_key.public_key().verify(base64.b64decode(license_doc['signature']),b'growthmap-revocation-v1\0'+json.dumps({k:license_doc[k] for k in sorted(license_doc) if k!='signature'},sort_keys=True,separators=(',',':')).encode())

def test_candidate_check_in_refreshes_only_active_license(env):
 s,c=env;o=s.create_order('paypal','checkin@e.test');assert s.candidate_check_in(o['recovery_code'])['state']=='not_found_or_unavailable';s.paypal_submit(o['order_id'],'CHECKIN');issued=s.paypal_confirm(o['order_id'],'CHECKIN',{'amount':'10','currency':'USD','status':'COMPLETED','payee_verified':True});fresh=s.candidate_check_in(o['recovery_code']);assert fresh['state']=='license_issued' and fresh['license']['license_id']==issued['license_id'];s.admin_transition(o['order_id'],'revoke');assert s.candidate_check_in(o['recovery_code'])['state']=='not_found_or_unavailable'

def test_populated_authenticated_v6_upgrades_to_v7_and_reopens(tmp_path,monkeypatch):
 import growthmap_payments.service as module
 p=tmp_path/'populated-v6.sqlite';c=config(p);monkeypatch.setattr(module,'SCHEMA_VERSION',6);v6=PaymentService(c);o=v6.create_order('paypal','v6@e.test');v6.paypal_submit(o['order_id'],'V6-TX');issued=v6.paypal_confirm(o['order_id'],'V6-TX',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});assert issued['state']=='license_issued'
 monkeypatch.setattr(module,'SCHEMA_VERSION',7);v7=PaymentService(c)
 with v7._db() as db:
  assert db.execute('PRAGMA user_version').fetchone()[0]==7
  assert tuple(db.execute('SELECT version,filename,checksum FROM migration_ledger WHERE version=7').fetchone())==(7,*module.MIGRATIONS[7])
  assert db.execute('SELECT count(*) FROM revocation_assertions').fetchone()[0]==0
 reopened=PaymentService(c);assert reopened.recovery_lookup(o['recovery_code'])['license']['license_id']==issued['license_id']

def test_migration_007_delete_reinsert_checkpoint_failure_and_tamper(tmp_path,monkeypatch):
 p=tmp_path/'migration-007-security.sqlite';c=config(p);s=PaymentService(c);o=s.create_order('paypal','m7@e.test');s.paypal_submit(o['order_id'],'M7-TX');s.paypal_confirm(o['order_id'],'M7-TX',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});a=s.admin_transition(o['order_id'],'revoke')['revocation']
 with s._db() as db:
  with pytest.raises(sqlite3.IntegrityError,match='immutable'):db.execute('DELETE FROM revocation_assertions')
  with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO revocation_assertions SELECT * FROM revocation_assertions")
 with sqlite3.connect(p) as db:db.execute('DROP TRIGGER revocation_assertion_no_delete');db.execute('DELETE FROM revocation_assertions')
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c)
 # A checkpoint publication failure rolls back insertion and permanently closes the instance.
 p2=tmp_path/'migration-007-checkpoint.sqlite';c2=config(p2);s2=PaymentService(c2);o2=s2.create_order('paypal','m7-fail@e.test');s2.paypal_submit(o2['order_id'],'M7-FAIL');s2.paypal_confirm(o2['order_id'],'M7-FAIL',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True})
 monkeypatch.setattr(s2,'_write_checkpoint_document',lambda _doc:(_ for _ in ()).throw(OSError('injected')))
 with pytest.raises(RuntimeError,match='checkpoint update failed'):s2.admin_transition(o2['order_id'],'revoke')
 with sqlite3.connect(p2) as db:assert db.execute('SELECT count(*) FROM revocation_assertions').fetchone()[0]==0
 with pytest.raises(RuntimeError,match='fail-closed'):s2.recovery_lookup(o2['recovery_code'])
 # Reinserted byte-tampered assertion is covered by the authenticated closure.
 p3=tmp_path/'migration-007-tamper.sqlite';c3=config(p3);s3=PaymentService(c3);o3=s3.create_order('paypal','m7-tamper@e.test');s3.paypal_submit(o3['order_id'],'M7-TAMPER');s3.paypal_confirm(o3['order_id'],'M7-TAMPER',{'amount':'10.00','currency':'USD','status':'COMPLETED','payee_verified':True});s3.admin_transition(o3['order_id'],'revoke')
 with sqlite3.connect(p3) as db:db.execute('DROP TRIGGER revocation_assertion_no_update');db.execute("UPDATE revocation_assertions SET assertion_json=replace(assertion_json,'administrative','fraud')")
 with pytest.raises(RuntimeError,match='checkpoint/database mismatch'):PaymentService(c3)
