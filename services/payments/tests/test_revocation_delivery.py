import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from test_device_activation_closure import setup, paid
from licensing.authority import activation_challenge


def keypair():
 key=Ed25519PrivateKey.generate();public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();return key,public

def signed(key,license_id,public,nonce):return base64.b64encode(key.sign(activation_challenge(license_id,public,nonce))).decode()

def test_refund_before_delivery_is_atomic_cancel_and_never_creates_license(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);claimed=service.claim_outbox("old-worker",order_id=order["order_id"])
 result=service.admin_transition(order["order_id"],"refund");assert result["revocation_event"] is None
 with service._db() as db:
  assert db.execute("select state from orders where id=?",(order["order_id"],)).fetchone()[0]=="refunded"
  assert db.execute("select state from entitlement_outbox where order_id=?",(order["order_id"],)).fetchone()[0]=="quarantined"
  assert db.execute("select count(*) from revocation_outbox").fetchone()[0]==0
 with pytest.raises(RuntimeError,match="lease lost"):service.deliver_claimed_outbox(claimed,authority,"old-worker")
 with authority._connect() as db:assert db.execute("select count(*) from licenses").fetchone()[0]==0
 assert service.admin_transition(order["order_id"],"refund")["idempotent"]


def test_revocation_ack_crash_reclaim_stale_fence_and_100_replay(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);transition=service.admin_transition(order["order_id"],"revoke","fraud");assert transition["revocation_event"]["state"]=="pending"
 stale=service.claim_revocation("stale",lease_seconds=-1,order_id=order["order_id"]);fresh=service.claim_revocation("fresh",lease_seconds=-1,order_id=order["order_id"]);assert fresh["fencing_version"]>stale["fencing_version"]
 with pytest.raises(RuntimeError,match="lease lost"):service.deliver_claimed_revocation(stale,authority,"stale")
 # Authority commit followed by payment-ack crash: replay after lease expiry.
 receipt=authority.revoke_external_entitlement(source=fresh["source"],source_id=fresh["source_id"],payload_digest=fresh["entitlement_payload_digest"],authority_id=fresh["authority_id"],license_id=fresh["license_id"],action=fresh["action"],reason=fresh["reason"],payment_proof=fresh["proof_hash"],tx_hash=fresh["tx_hash"],created_at=fresh["created_at"])
 reclaimed=service.claim_revocation("reclaim",order_id=order["order_id"]);acked=service.deliver_claimed_revocation(reclaimed,authority,"reclaim");assert acked==receipt
 with ThreadPoolExecutor(20) as pool:replays=list(pool.map(lambda _:authority.revoke_external_entitlement(source=fresh["source"],source_id=fresh["source_id"],payload_digest=fresh["entitlement_payload_digest"],authority_id=fresh["authority_id"],license_id=fresh["license_id"],action=fresh["action"],reason=fresh["reason"],payment_proof=fresh["proof_hash"],tx_hash=fresh["tx_hash"],created_at=fresh["created_at"]),range(100)))
 assert {x["revocation_receipt"] for x in replays}=={receipt["revocation_receipt"]}
 with authority._connect() as db:
  assert db.execute("select count(*) from external_revocations").fetchone()[0]==1
  assert db.execute("select count(*) from licenses where revoked_at is not null").fetchone()[0]==1
 with service._db() as db:assert tuple(db.execute("select state,authority_receipt from revocation_outbox").fetchone())==("delivered",receipt["revocation_receipt"])
 # A delivered ack is immutable/no-delete.
 with pytest.raises(Exception):
  with service._db() as db:db.execute("delete from revocation_outbox")


def test_revocation_retry_backoff_then_delivery(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);service.deliver_entitlement(order["order_id"],authority);service.admin_transition(order["order_id"],"revoke")
 row=service.claim_revocation("retry",order_id=order["order_id"]);service.fail_revocation(row,"retry","temporary authority outage")
 with service._db() as db:
  state=tuple(db.execute("select state,attempt_count,last_error_hash from revocation_outbox").fetchone());assert state[0]=="pending" and state[1]==1 and state[2]
  db.execute("BEGIN IMMEDIATE");db.execute("update revocation_outbox set next_attempt_at=?",("2000-01-01T00:00:00+00:00",));service._commit_trusted(db)
 assert service.deliver_revocation(order["order_id"],authority)["revocation_receipt"]


def test_full_payment_activation_revoke_blocks_all_new_activation_paths(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority)
 first_key,first_public=keypair();first_ch=authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=first_public);authority.activate_challenge(challenge_id=first_ch["challenge_id"],proof=signed(first_key,ent["license_id"],first_public,first_ch["nonce"]))
 outstanding_key,outstanding_public=keypair();outstanding=authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=outstanding_public)
 service.admin_transition(order["order_id"],"refund");service.deliver_revocation(order["order_id"],authority)
 second_key,second_public=keypair()
 with pytest.raises(ValueError,match="license_unavailable"):authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=second_public)
 with pytest.raises(ValueError,match="license_revoked"):authority.activate_challenge(challenge_id=outstanding["challenge_id"],proof=signed(outstanding_key,ent["license_id"],outstanding_public,outstanding["nonce"]))
 nonce="direct_nonce_123456789"
 with pytest.raises(ValueError,match="license_revoked"):authority.activate(license_id=ent["license_id"],device_public_key=second_public,nonce=nonce,proof=signed(second_key,ent["license_id"],second_public,nonce))
 with authority._connect() as db:assert db.execute("select revoked_at from licenses where license_id=?",(ent["license_id"],)).fetchone()[0]


def test_expired_challenge_and_explicit_one_two_three_seat_matrix(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);key,public=keypair();expired=authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=public,ttl_seconds=-1)
 with pytest.raises(ValueError,match="challenge_expired"):authority.activate_challenge(challenge_id=expired["challenge_id"],proof=signed(key,ent["license_id"],public,expired["nonce"]))
 for seat in (1,2,3):
  key,public=keypair();challenge=authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=public);proof=signed(key,ent["license_id"],public,challenge["nonce"])
  if seat<3:assert authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof)["device_allowance"]==2
  else:
   with pytest.raises(ValueError,match="seat_limit_reached"):authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof)


@pytest.mark.parametrize("field",["outcome","evidence_hash","source","finality_at","finality_basis","payer","proof_hash","nonce_hash","order_id"])
def test_reconciler_wrong_or_missing_field_matrix(field,tmp_path):
 service,_,_=setup(tmp_path);order=service.create_order("x402","matrix@example.test");intent=service.prepare_x402_intent(order["order_id"],"matrix-proof","matrix-nonce",10_000_000,"0x"+"2"*40);service.mark_intent_ambiguous(intent["intent_id"],"matrix")
 class Wrong:
  def reconcile(self,row):
   evidence={"outcome":"paid","tx_hash":"0x"+"9"*64,"evidence_hash":"matrix-evidence","source":"authenticated-fixture","finality_at":service.now(),"finality_basis":"fixture-receipt","payer":row["verified_payer"],"proof_hash":row["proof_hash"],"nonce_hash":row["nonce_hash"],"order_id":row["order_id"]}
   if field in {"proof_hash","nonce_hash","order_id","payer"}:evidence[field]="wrong"
   else:evidence.pop(field)
   return evidence
 with pytest.raises((ValueError,KeyError)):service.reconcile_intent(intent["intent_id"],Wrong(),"admin-fixture")
 with service._db() as db:assert db.execute("select state from settlement_intents where intent_id=?",(intent["intent_id"],)).fetchone()[0]=="ambiguous"


def _revocation_args(service, entitlement, action="revoke", reason="fraud"):
 with service._db() as db: row=dict(db.execute("select * from entitlement_outbox").fetchone())
 return dict(source=row["source"],source_id=row["source_id"],payload_digest=service._outbox_payload_digest(row),authority_id=service.config.authority_id,license_id=entitlement["license_id"],action=action,reason=reason,payment_proof=row["proof_hash"],tx_hash=row["tx_hash"],created_at=row["created_at"])


def test_revoke_writer_wins_challenge_has_zero_activation_side_effect(tmp_path,monkeypatch):
 service,issuer,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],issuer)
 revoker=type(issuer)(issuer.database,tmp_path/"issuer.pem");activator=type(issuer)(issuer.database,tmp_path/"issuer.pem")
 key,public=keypair();challenge=activator.issue_activation_challenge(license_id=ent["license_id"],device_public_key=public);proof=signed(key,ent["license_id"],public,challenge["nonce"])
 locked=__import__("threading").Event();release=__import__("threading").Event();original=revoker._audit
 def pause(db,event,*args,**kwargs):
  if event=="external_entitlement_revoked":locked.set();assert release.wait(5)
  return original(db,event,*args,**kwargs)
 monkeypatch.setattr(revoker,"_audit",pause);out={}
 with ThreadPoolExecutor(2) as pool:
  revoke_future=pool.submit(revoker.revoke_external_entitlement,**_revocation_args(service,ent));assert locked.wait(5)
  activate_future=pool.submit(activator.activate_challenge,challenge_id=challenge["challenge_id"],proof=proof);release.set();out["revoke"]=revoke_future.result()
  with pytest.raises(ValueError,match="license_revoked"):activate_future.result()
 with activator._connect() as db:
  assert db.execute("select count(*) from activations where deactivated_at is null").fetchone()[0]==0
  assert db.execute("select count(*) from activation_requests").fetchone()[0]==0
  assert db.execute("select certificate_json from activation_challenges where challenge_id=?",(challenge["challenge_id"],)).fetchone()[0] is None


def test_activation_writer_wins_then_revoke_deactivates_and_denies_retrieval(tmp_path,monkeypatch):
 service,issuer,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],issuer)
 activator=type(issuer)(issuer.database,tmp_path/"issuer.pem");revoker=type(issuer)(issuer.database,tmp_path/"issuer.pem")
 key,public=keypair();challenge=activator.issue_activation_challenge(license_id=ent["license_id"],device_public_key=public);proof=signed(key,ent["license_id"],public,challenge["nonce"])
 locked=__import__("threading").Event();release=__import__("threading").Event();original=activator._activate_in_transaction
 def pause(*args,**kwargs):
  cert=original(*args,**kwargs);locked.set();assert release.wait(5);return cert
 monkeypatch.setattr(activator,"_activate_in_transaction",pause)
 with ThreadPoolExecutor(2) as pool:
  activate_future=pool.submit(activator.activate_challenge,challenge_id=challenge["challenge_id"],proof=proof);assert locked.wait(5)
  revoke_future=pool.submit(revoker.revoke_external_entitlement,**_revocation_args(service,ent));release.set();cert=activate_future.result();revoke_future.result()
 assert cert["revoked_at"] is None  # immutable signed historical bytes
 with activator._connect() as db:
  assert db.execute("select count(*) from activations where deactivated_at is null").fetchone()[0]==0
  assert db.execute("select status from activation_requests").fetchone()[0]=="consumed"
 with pytest.raises(ValueError,match="license_revoked"):activator.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof)
 with pytest.raises(ValueError,match="license_revoked"):activator.activate(license_id=ent["license_id"],device_public_key=public,nonce=challenge["nonce"],proof=proof)


def test_challenge_wrong_proof_rolls_back_and_exact_response_loss(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);key,public=keypair();challenge=authority.issue_activation_challenge(license_id=ent["license_id"],device_public_key=public)
 with pytest.raises(ValueError,match="device_proof_invalid"):authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=base64.b64encode(b"x"*64).decode())
 with authority._connect() as db:
  row=db.execute("select consumed_at,certificate_json from activation_challenges").fetchone();assert tuple(row)==(None,None);assert db.execute("select count(*) from activation_requests").fetchone()[0]==0
 proof=signed(key,ent["license_id"],public,challenge["nonce"]);first=authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof);second=authority.activate_challenge(challenge_id=challenge["challenge_id"],proof=proof);assert first==second


def test_authority_revocation_strict_shape_and_contradiction(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);args=_revocation_args(service,ent);first=authority.revoke_external_entitlement(**args);assert authority.revoke_external_entitlement(**args)==first
 for field,value,error in (("action","reject","invalid_revocation_action"),("reason","other","invalid_revocation_reason"),("license_id","bad id","invalid_revocation_evidence"),("payment_proof","no","invalid_revocation_evidence"),("tx_hash","no","invalid_revocation_evidence")):
  bad=dict(args);bad[field]=value
  with pytest.raises(ValueError,match=error):authority.revoke_external_entitlement(**bad)
 contradictory=dict(args);contradictory["reason"]="chargeback"
 with pytest.raises(ValueError,match="external_revocation_contradiction"):authority.revoke_external_entitlement(**contradictory)


def test_revocation_created_at_freshness_and_expired_exact_replay(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);args=_revocation_args(service,ent)
 for stamp in ((datetime.now(timezone.utc)+timedelta(minutes=6)).isoformat(),(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat(),datetime.now().isoformat()):
  bad=dict(args);bad["created_at"]=stamp
  with pytest.raises(ValueError,match="invalid_revocation_created_at"):authority.revoke_external_entitlement(**bad)
 first=authority.revoke_external_entitlement(**args)
 old_now=authority.now;authority.now=lambda: old_now()+timedelta(hours=25)
 assert authority.revoke_external_entitlement(**args)==first
 contradiction=dict(args);contradiction["reason"]="chargeback"
 with pytest.raises(ValueError,match="external_revocation_contradiction"):authority.revoke_external_entitlement(**contradiction)


def test_revocation_naive_authority_clock_fails_closed(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority);args=_revocation_args(service,ent);authority.now=lambda:datetime.now()
 with pytest.raises(RuntimeError,match="invalid_authority_clock"):authority.revoke_external_entitlement(**args)


def test_payment_rejects_stale_future_and_naive_revocation_creation(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority)
 with service._db() as db:
  row=db.execute("SELECT * FROM entitlement_outbox WHERE order_id=?",(order["order_id"],)).fetchone()
  for stamp in ((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),(datetime.now(timezone.utc)+timedelta(minutes=6)).isoformat(),datetime.now().isoformat()):
   with pytest.raises(ValueError,match="invalid revocation event time"):service._enqueue_revocation(db,row,ent["license_id"],"revoke","fraud",stamp)

def test_payment_revocation_uses_one_injected_aware_utc_clock(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);ent=service.deliver_entitlement(order["order_id"],authority)
 instant=datetime(2030,1,2,3,4,5,tzinfo=timezone(timedelta(hours=8)));service.now=lambda:instant.isoformat()
 result=service.admin_transition(order["order_id"],"revoke","fraud")
 assert result["revocation"]["revoked_at"]=="2030-01-01T19:04:05Z"
 assert result["revocation_event"]["created_at"]=="2030-01-01T19:04:05+00:00"

def test_payment_revocation_naive_injected_clock_fails_closed(tmp_path):
 service,authority,_=setup(tmp_path);order=paid(service);service.deliver_entitlement(order["order_id"],authority);service.now=lambda:datetime(2030,1,1)
 with pytest.raises(RuntimeError,match="invalid_payment_clock"):service.admin_transition(order["order_id"],"revoke","fraud")
