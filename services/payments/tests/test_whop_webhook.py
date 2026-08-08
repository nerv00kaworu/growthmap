import hashlib,json,re,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
import pytest
from growthmap_payments.api import create_app
from growthmap_payments.service import PaymentService
from growthmap_payments.whop import MAX_BODY_BYTES,MAX_SIGNATURE_HEADERS,WhopIngressError,bounded_request,bounded_signature_headers,parse_verified_event
from test_payments import config
from test_device_activation_closure import setup,paid

class Verifier:
 def __init__(self,bad=False):self.bad=bad;self.calls=0
 def verify(self,raw_body,signature_headers):
  self.calls+=1
  if self.bad:raise ValueError("bad")
  return raw_body

def body(order,event="evt-1",kind="paid",**changes):
 value={"event_id":event,"kind":kind,"occurred_at":"2026-08-08T00:00:00+00:00","order_id":order,"provider_order_ref":"wo-1","provider_payment_ref":"wp-1"};value.update(changes);return json.dumps(value,separators=(",",":")).encode()
def event(order,event_id="evt-1",kind="paid"):return parse_verified_event(body(order,event_id,kind))

def test_bounds_and_strict_authenticated_schema():
 with pytest.raises(WhopIngressError):bounded_request(b"x",{})
 with pytest.raises(WhopIngressError):bounded_request(b"x"*(MAX_BODY_BYTES+1),{"whop-signature":"x"})
 with pytest.raises(WhopIngressError):bounded_request(b"x",{"whop-signature":"x"*4097})
 with pytest.raises(WhopIngressError):bounded_signature_headers([(b"whop-signature",b"\xff")])
 with pytest.raises(WhopIngressError):bounded_signature_headers([(b"x"*129,b"v")])
 with pytest.raises(WhopIngressError):bounded_signature_headers([(f"whop-{i}".encode(),b"v") for i in range(MAX_SIGNATURE_HEADERS+1)])
 with pytest.raises(WhopIngressError):parse_verified_event(b'{"event_id":"a","EVENT_ID":"b"}')
 value=json.loads(body("order"));value["extra"]=1
 with pytest.raises(WhopIngressError):parse_verified_event(json.dumps(value).encode())

def test_route_fails_closed_verifies_before_store_and_generic(tmp_path):
 cfg=config(tmp_path/"p.sqlite");order=PaymentService(cfg).create_order("paypal","a@e.test")["order_id"]
 client=TestClient(create_app(cfg))
 assert client.post("/v1/webhooks/whop",content=body(order),headers={"whop-signature":"x"}).status_code==503
 bad=Verifier(True);client=TestClient(create_app(cfg,whop_verifier=bad))
 response=client.post("/v1/webhooks/whop",content=body(order),headers={"whop-signature":"x"})
 assert response.status_code==400 and response.json()=={"state":"not_accepted"} and response.headers["cache-control"]=="no-store"
 with PaymentService(cfg)._db() as db:assert db.execute("SELECT count(*) FROM whop_webhook_inbox").fetchone()[0]==0
 assert client.post("/v1/webhooks/whop",content=b"x"*(MAX_BODY_BYTES+1),headers={"whop-signature":"x"}).status_code==400

def test_duplicate_concurrent_exactly_once_and_conflict(tmp_path):
 svc=PaymentService(config(tmp_path/"p.sqlite"));order=svc.create_order("paypal","a@e.test")["order_id"]
 # Paid cannot mint from an unreviewed Whop checkout binding; retries converge to quarantine.
 ev=event(order);digest=hashlib.sha256(body(order)).hexdigest()
 with ThreadPoolExecutor(max_workers=20) as pool:results=list(pool.map(lambda _:svc.receive_whop_event(ev,digest),range(100)))
 assert {r["state"] for r in results}<={"received","quarantined"}
 with svc._db() as db:
  row=db.execute("SELECT * FROM whop_webhook_inbox").fetchone();assert row["attempts"]==3 and row["state"]=="quarantined"
  assert db.execute("SELECT count(*) FROM whop_webhook_inbox").fetchone()[0]==1
 with pytest.raises(ValueError):svc.receive_whop_event(parse_verified_event(body(order,"evt-1","refund")),hashlib.sha256(body(order,"evt-1","refund")).hexdigest())

def test_reversal_before_paid_and_terminal_monotonicity(tmp_path):
 for kind in ("refund","dispute","chargeback"):
  svc=PaymentService(config(tmp_path/f"{kind}.sqlite"));oid=svc.create_order("paypal",f"{kind}@e.test")["order_id"]
  raw=body(oid,"reverse",kind);assert svc.receive_whop_event(parse_verified_event(raw),hashlib.sha256(raw).hexdigest())["state"]=="applied"
  paid=body(oid,"late","paid",provider_payment_ref="wp-2");assert svc.receive_whop_event(parse_verified_event(paid),hashlib.sha256(paid).hexdigest())["state"]=="applied"
  with svc._db() as db:
   expected="refunded" if kind=="refund" else "revoked";assert db.execute("SELECT state FROM orders WHERE id=?",(oid,)).fetchone()[0]==expected
   assert db.execute("SELECT count(*) FROM payment_proofs WHERE order_id=?",(oid,)).fetchone()[0]==0

@pytest.mark.parametrize("kind",["dispute","chargeback"])
def test_reversal_after_crossing_authorized_response_loss_compensates(tmp_path,monkeypatch,kind):
 svc,authority,_=setup(tmp_path);order=paid(svc);original=authority.create_external_entitlement
 def mint_then_reverse(**kwargs):
  result=original(**kwargs);raw=body(order["order_id"],"reverse-after-crossing",kind)
  assert svc.receive_whop_event(parse_verified_event(raw),hashlib.sha256(raw).hexdigest())["state"]=="applied"
  raise RuntimeError("response lost")
 monkeypatch.setattr(authority,"create_external_entitlement",mint_then_reverse)
 entitlement=svc.deliver_entitlement(order["order_id"],authority)
 with svc._db() as db:
  assert tuple(db.execute("SELECT state,license_id FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("delivered",entitlement["license_id"])
  assert tuple(db.execute("SELECT action,reason,state FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("revoke","chargeback","pending")
  assert db.execute("SELECT state FROM orders WHERE id=?",(order["order_id"],)).fetchone()[0]=="revoked"
 with authority._connect() as db:assert db.execute("SELECT count(*) FROM licenses WHERE license_id=?",(entitlement["license_id"],)).fetchone()[0]==1

@pytest.mark.parametrize("kind",["dispute","chargeback"])
def test_restart_recovers_revoked_crossing_by_readback_only(tmp_path,monkeypatch,kind):
 svc,authority,cfg=setup(tmp_path);order=paid(svc);creates=0;original=authority.create_external_entitlement
 def mint_reverse_crash(**kwargs):
  nonlocal creates
  creates+=1;result=original(**kwargs);raw=body(order["order_id"],"crash-reversal",kind)
  assert svc.receive_whop_event(parse_verified_event(raw),hashlib.sha256(raw).hexdigest())["state"]=="applied"
  raise SystemExit("simulated process crash before acknowledgement persistence")
 monkeypatch.setattr(authority,"create_external_entitlement",mint_reverse_crash)
 claimed=svc.claim_outbox("crashing",order_id=order["order_id"])
 with pytest.raises(SystemExit):svc.deliver_claimed_outbox(claimed,authority,"crashing")
 assert creates==1
 with svc._db() as db:
  assert tuple(db.execute("SELECT state,reconciliation_phase FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("quarantined","readback_only")
  assert db.execute("SELECT state FROM orders WHERE id=?",(order["order_id"],)).fetchone()[0]=="revoked"
  db.execute("BEGIN IMMEDIATE");db.execute("UPDATE entitlement_outbox SET next_attempt_at=? WHERE order_id=?",("2000-01-01T00:00:00+00:00",order["order_id"]));svc._commit_trusted(db)
 restart=PaymentService(cfg)
 def never_create(**kwargs):raise AssertionError("revoked readback recovery attempted create")
 monkeypatch.setattr(authority,"create_external_entitlement",never_create)
 stale=restart.claim_outbox("stale",lease_seconds=-1,order_id=order["order_id"]);fresh=restart.claim_outbox("fresh",order_id=order["order_id"])
 with pytest.raises(RuntimeError,match="lease lost"):restart.deliver_claimed_outbox(stale,authority,"stale")
 entitlement=restart.deliver_claimed_outbox(fresh,authority,"fresh");assert creates==1
 with restart._db() as db:
  outbox=db.execute("SELECT state,license_id,delivery_receipt,authority_ack_signature FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone();assert outbox[0]=="delivered" and outbox[1]==entitlement["license_id"] and outbox[2] and outbox[3]
  assert db.execute("SELECT state FROM orders WHERE id=?",(order["order_id"],)).fetchone()[0]=="revoked"
  assert tuple(db.execute("SELECT action,reason,state FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("revoke","chargeback","pending")
  assert db.execute("SELECT count(*) FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone()[0]==1
 restart._verify_or_initialize_checkpoint()
 assert restart.deliver_entitlement(order["order_id"],authority)["license_id"]==entitlement["license_id"]
 with restart._db() as db:assert db.execute("SELECT count(*) FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone()[0]==1

def _force_entitlement_due(service,order_id):
 with service._db() as db:
  db.execute("BEGIN IMMEDIATE");db.execute("UPDATE entitlement_outbox SET next_attempt_at=? WHERE order_id=?",("2000-01-01T00:00:00+00:00",order_id));service._commit_trusted(db)

def _prepare_revoked_readback(tmp_path,monkeypatch,kind):
 svc,authority,cfg=setup(tmp_path);order=paid(svc);original=authority.create_external_entitlement;creates=[0]
 def crash(**kwargs):
  creates[0]+=1;original(**kwargs);raw=body(order["order_id"],"readback-failure-reversal",kind);svc.receive_whop_event(parse_verified_event(raw),hashlib.sha256(raw).hexdigest());raise SystemExit
 monkeypatch.setattr(authority,"create_external_entitlement",crash);claimed=svc.claim_outbox("crash",order_id=order["order_id"])
 with pytest.raises(SystemExit):svc.deliver_claimed_outbox(claimed,authority,"crash")
 monkeypatch.setattr(authority,"create_external_entitlement",lambda **kwargs:(_ for _ in ()).throw(AssertionError("readback recovery attempted create")))
 _force_entitlement_due(svc,order["order_id"]);return svc,authority,cfg,order,creates

@pytest.mark.parametrize("kind",["dispute","chargeback"])
@pytest.mark.parametrize("invalid",["raises","missing","shape","no_signature","bad_signature","identity","source","payload","receipt"])
def test_invalid_revoked_readback_remains_retryable_without_evidence(tmp_path,monkeypatch,kind,invalid):
 svc,authority,_,order,creates=_prepare_revoked_readback(tmp_path,monkeypatch,kind);original=authority.read_external_entitlement_acknowledgement
 def bad(**kwargs):
  if invalid=="raises":raise RuntimeError("missing readback")
  ack=original(**kwargs)
  if invalid=="missing":return None
  ack=dict(ack)
  if invalid=="shape":ack["extra"]="x"
  elif invalid=="no_signature":ack.pop("ack_signature")
  elif invalid=="bad_signature":ack["ack_signature"]="A"*88
  elif invalid=="identity":ack["signer_identity"]={**ack["signer_identity"],"generation":999}
  elif invalid=="source":ack["source"]="wrong"
  elif invalid=="payload":ack["payload_digest"]="0"*64
  elif invalid=="receipt":ack["delivery_receipt"]="0"*64
  return ack
 monkeypatch.setattr(authority,"read_external_entitlement_acknowledgement",bad)
 with pytest.raises(RuntimeError):svc.deliver_entitlement(order["order_id"],authority)
 assert creates==[1]
 with svc._db() as db:
  row=db.execute("SELECT state,reconciliation_phase,next_attempt_at,last_error_hash,license_id,delivery_receipt,authority_ack_signature FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone();assert row[0:2]==("quarantined","readback_only") and row[2] and row[4:]==(None,None,None)
  due=datetime.fromisoformat(row[2]);now=datetime.now(timezone.utc);assert now<due<=now+timedelta(seconds=5) and re.fullmatch(r"[a-f0-9]{64}",row[3])
  assert db.execute("SELECT count(*) FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone()[0]==0
  assert db.execute("SELECT state FROM orders WHERE id=?",(order["order_id"],)).fetchone()[0]=="revoked"
 svc._verify_or_initialize_checkpoint();_force_entitlement_due(svc,order["order_id"]);monkeypatch.setattr(authority,"read_external_entitlement_acknowledgement",original)
 entitlement=svc.deliver_entitlement(order["order_id"],authority);assert creates==[1]
 with svc._db() as db:
  assert db.execute("SELECT count(*) FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone()[0]==1
  assert tuple(db.execute("SELECT action,reason FROM revocation_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("revoke","chargeback")
 svc._verify_or_initialize_checkpoint();assert svc.deliver_entitlement(order["order_id"],authority)["license_id"]==entitlement["license_id"]

@pytest.mark.parametrize("kind",["dispute","chargeback"])
def test_invalid_revoked_readback_bounded_to_manual_review_and_stale_fence_safe(tmp_path,monkeypatch,kind):
 svc,authority,_,order,creates=_prepare_revoked_readback(tmp_path,monkeypatch,kind)
 monkeypatch.setattr(authority,"read_external_entitlement_acknowledgement",lambda **kwargs:None)
 stale=svc.claim_outbox("stale",lease_seconds=-1,order_id=order["order_id"]);fresh=svc.claim_outbox("fresh",order_id=order["order_id"])
 with pytest.raises(RuntimeError,match="lease lost"):svc.deliver_claimed_outbox(stale,authority,"stale")
 with pytest.raises(RuntimeError):svc.deliver_claimed_outbox(fresh,authority,"fresh")
 svc.fail_outbox(fresh,"fresh","duplicate stale failure")
 while True:
  with svc._db() as db:phase=db.execute("SELECT reconciliation_phase FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone()[0]
  if phase=="manual_review":break
  _force_entitlement_due(svc,order["order_id"]);claimed=svc.claim_outbox("retry",order_id=order["order_id"]);assert claimed is not None
  with pytest.raises(RuntimeError):svc.deliver_claimed_outbox(claimed,authority,"retry")
  svc.fail_outbox(claimed,"retry","duplicate retry failure")
 with svc._db() as db:
  row=db.execute("SELECT state,reconciliation_phase,attempt_count,license_id,delivery_receipt,authority_ack_signature FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone();assert row[0:3]==("quarantined","manual_review",8) and row[3:]==(None,None,None)
  assert db.execute("SELECT count(*) FROM revocation_outbox").fetchone()[0]==0
 assert creates==[1] and svc.claim_outbox("never",order_id=order["order_id"]) is None
 rows=svc.list_authority_reconciliation("manual_review");assert len(rows)==1 and rows[0]["order_id"]==order["order_id"] and rows[0]["reconciliation_phase"]=="manual_review"
 svc._verify_or_initialize_checkpoint()

@pytest.mark.parametrize("kind",["dispute","chargeback"])
def test_blocked_stale_readback_exception_cannot_requeue_fresh_fence(tmp_path,monkeypatch,kind):
 svc,authority,_,order,_=_prepare_revoked_readback(tmp_path,monkeypatch,kind);entered=threading.Event();release=threading.Event();calls=[0]
 def blocked(**kwargs):
  calls[0]+=1
  if calls[0]==1:entered.set();assert release.wait(5)
  raise RuntimeError("readback outage")
 monkeypatch.setattr(authority,"read_external_entitlement_acknowledgement",blocked)
 stale=svc.claim_outbox("stale",lease_seconds=-1,order_id=order["order_id"])
 with ThreadPoolExecutor(1) as pool:
  future=pool.submit(svc.deliver_claimed_outbox,stale,authority,"stale");assert entered.wait(5);fresh=svc.claim_outbox("fresh",order_id=order["order_id"]);release.set()
  with pytest.raises(RuntimeError,match="authority_reconciliation_state_lost"):future.result()
 with svc._db() as db:assert tuple(db.execute("SELECT state,lease_owner,fencing_version,reconciliation_phase FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("leased","fresh",fresh["fencing_version"],"readback_only")
 svc.fail_outbox(stale,"stale","stale outer failure")
 with svc._db() as db:assert tuple(db.execute("SELECT state,lease_owner,fencing_version FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("leased","fresh",fresh["fencing_version"])
 with pytest.raises(RuntimeError,match="authority_reconciliation_pending"):svc.deliver_claimed_outbox(fresh,authority,"fresh")
 with svc._db() as db:assert tuple(db.execute("SELECT state,lease_owner,reconciliation_phase FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone())==("quarantined",None,"readback_only")
 svc._verify_or_initialize_checkpoint()

def test_response_loss_replay_and_admin_readback(tmp_path):
 cfg=config(tmp_path/"p.sqlite");svc=PaymentService(cfg);oid=svc.create_order("paypal","a@e.test")["order_id"]
 raw=body(oid,"refund","refund");verifier=Verifier();client=TestClient(create_app(cfg,whop_verifier=verifier))
 assert client.post("/v1/webhooks/whop",content=raw,headers={"whop-signature":"fixture"}).status_code==202
 assert client.post("/v1/webhooks/whop",content=raw,headers={"whop-signature":"fixture"}).status_code==202
 rows=client.get("/v1/admin/whop-inbox",headers={"Authorization":"Bearer secret","X-CSRF-Token":"fixture-csrf","Origin":"https://admin.test"}).json()
 assert len(rows)==1 and rows[0]["state"]=="applied" and "raw_digest" not in rows[0]
