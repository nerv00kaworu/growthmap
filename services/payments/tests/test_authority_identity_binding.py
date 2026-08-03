import hashlib, time
from datetime import datetime, timezone
from dataclasses import replace
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from licensing.authority import LicenseAuthority
from licensing.signer_ceremony import DOMAIN, PURPOSE, OfflineFixtureMonotonicAnchor
from test_device_activation_closure import paid
from test_payments import config
from growthmap_payments.service import PaymentService

class Signer:
 def __init__(self,key):self.key=key
 def sign(self,message):return self.key.sign(message)
def signer_setup(**changes):
 key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo);descriptor={'schema_version':1,'purpose':PURPOSE,'domain':DOMAIN,'algorithm':'Ed25519','authority_id':'growthmap-authority-primary','key_id':'issuer-1','generation':1,'activated_at':'2026-08-02T00:00:00Z','predecessor_generation':None,'public_key_sha256':hashlib.sha256(public).hexdigest(),'provider_attestation_id':'kms:review-1'};descriptor.update(changes);return key,public,descriptor
def make_authority(path,key,public,descriptor,anchor):return LicenseAuthority.from_external_signer(path,signer=Signer(key),ceremony_descriptor=descriptor,reviewed_public_key=public,generation_anchor=anchor,now=lambda:datetime.now(timezone.utc))


def identity(authority):return authority.handshake()
def configured(path,authority):
 i=identity(authority)|{'public_key':authority.public_key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)};return PaymentService(config(path,authority_identity=i))

def test_wrong_valid_authority_same_name_cannot_issue_and_identity_is_durable(tmp_path):
 k1,p1,d1=signer_setup();right=make_authority(tmp_path/'right.sqlite',k1,p1,d1,OfflineFixtureMonotonicAnchor())
 k2,p2,d2=signer_setup(key_id='wrong-key');wrong=make_authority(tmp_path/'wrong.sqlite',k2,p2,d2,OfflineFixtureMonotonicAnchor())
 service=configured(tmp_path/'payments.sqlite',right);order=paid(service)
 with pytest.raises(RuntimeError,match='authority_identity_mismatch'):service.deliver_entitlement(order['order_id'],wrong)
 with service._db() as db:
  assert db.execute('select state from orders').fetchone()[0]=='payment_confirmed'
  row=dict(db.execute('select * from entitlement_outbox').fetchone());assert row['state']=='pending'
  expected=identity(right);assert (row['authority_id'],row['authority_key_id'],row['authority_generation'],row['authority_public_key_sha256'],row['authority_attestation'])==tuple(expected.values())
 time.sleep(2.1)
 entitlement=service.deliver_entitlement(order['order_id'],right);assert entitlement['signer_identity']==identity(right)
 with right._connect() as db:
  row=db.execute('select * from external_entitlements').fetchone();assert (row['authority_id'],row['signer_key_id'],row['signer_generation'],row['signer_public_key_sha256'],row['signer_attestation'])==tuple(identity(right).values())


def test_revocation_rejects_wrong_identity_and_receipts_bind_generation(tmp_path):
 k1,p1,d1=signer_setup();right=make_authority(tmp_path/'right.sqlite',k1,p1,d1,OfflineFixtureMonotonicAnchor())
 k2,p2,d2=signer_setup(key_id='wrong-key');wrong=make_authority(tmp_path/'wrong.sqlite',k2,p2,d2,OfflineFixtureMonotonicAnchor())
 right.now=lambda:datetime.now(timezone.utc);wrong.now=lambda:datetime.now(timezone.utc)
 service=configured(tmp_path/'payments.sqlite',right);order=paid(service);service.deliver_entitlement(order['order_id'],right);service.admin_transition(order['order_id'],'revoke','administrative')
 with pytest.raises(RuntimeError,match='authority_identity_mismatch'):service.deliver_revocation(order['order_id'],wrong)
 with service._db() as db:assert db.execute('select state from revocation_outbox').fetchone()[0]=='pending'
 time.sleep(2.1)
 receipt=service.deliver_revocation(order['order_id'],right);assert receipt['signer_identity']==identity(right)
 with right._connect() as db:
  row=db.execute('select * from external_revocations').fetchone();assert (row['signer_key_id'],row['signer_generation'],row['signer_public_key_sha256'],row['signer_attestation'])==tuple(list(identity(right).values())[1:])


def test_fabricated_or_malformed_operation_cannot_transition(tmp_path):
 k,p,d=signer_setup();right=make_authority(tmp_path/'right.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',right);order=paid(service)
 class Fake:
  def handshake(self):return identity(right)
  def create_external_entitlement(self,**kwargs):return {'license_id':'gm_'+'a'*32,'edition':'personal','major_version':1,'device_allowance':2,'delivery_receipt':'0'*64,'authority_id':identity(right)['authority_id'],'signer_identity':identity(right)}
  def read_external_entitlement_acknowledgement(self,**kwargs):raise ValueError('not persisted SECRET')
 with pytest.raises(RuntimeError,match='authority_reconciliation_pending'):service.deliver_entitlement(order['order_id'],Fake())
 with service._db() as db:assert db.execute('select state from orders').fetchone()[0]=='payment_confirmed' and tuple(db.execute('select state,reconciliation_phase from entitlement_outbox').fetchone())==('quarantined','readback_only')

def test_response_shape_receipt_and_handshake_call_swap_fail_closed(tmp_path):
 k,p,d=signer_setup();right=make_authority(tmp_path/'right.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',right);order=paid(service)
 class Proxy:
  calls=0
  def handshake(self):
   self.calls+=1;return identity(right) if self.calls<2 else identity(right)|{'key_id':'swapped'}
  def create_external_entitlement(self,**kwargs):
   value=right.create_external_entitlement(**kwargs);return value|{'extra':'bad'}
  def read_external_entitlement_acknowledgement(self,**kwargs):return right.read_external_entitlement_acknowledgement(**kwargs)
 with pytest.raises(RuntimeError,match='identity|acknowledgement'):service.deliver_entitlement(order['order_id'],Proxy())

def test_handshake_shape_and_config_are_fail_closed(tmp_path):
 k,p,d=signer_setup();right=make_authority(tmp_path/'right.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',right);order=paid(service)
 class Extra:
  def handshake(self):return identity(right)|{'provider_detail':'secret'}
 with pytest.raises(RuntimeError,match='authority_identity_mismatch'):service.deliver_entitlement(order['order_id'],Extra())
 with pytest.raises(RuntimeError,match='expected Authority signer identity'):PaymentService(replace(config(tmp_path/'bad.sqlite'),authority_key_id=None))

def test_revocation_delivered_fast_path_reverifies_persisted_evidence(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.deliver_entitlement(order['order_id'],authority);service.admin_transition(order['order_id'],'revoke','administrative');good=service.deliver_revocation(order['order_id'],authority);assert service.deliver_revocation(order['order_id'],authority)==good
 for column,value in [('authority_ack_signature','!'*88),('authority_revoked_at','not-a-time'),('authority_request_digest','0'*64),('authority_receipt','0'*64)]:
  clone=tmp_path/f'{column}.sqlite'
  with service._db() as source, __import__('sqlite3').connect(clone) as destination:source.backup(destination)
  checkpoint=tmp_path/f'{column}.checkpoint';checkpoint.write_bytes(service.config.settlement_checkpoint_path.read_bytes());copy=PaymentService(replace(service.config,db_path=clone,settlement_checkpoint_path=checkpoint))
  with copy._db() as db:
   db.execute('drop trigger revocation_outbox_authority_ack_once');db.execute('drop trigger revocation_outbox_authority_result_once');db.execute('drop trigger revocation_outbox_ack_once');db.execute(f'update revocation_outbox set {column}=?',(value,));copy._write_checkpoint_document(copy._checkpoint_document(db));db.commit()
  with pytest.raises(RuntimeError,match='acknowledgement'):copy.deliver_revocation(order['order_id'],authority)

def test_refund_preserves_crossing_phase_and_restart_readback_compensates(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service)
 class Loss:
  reads=0
  def handshake(self):return authority.handshake()
  def create_external_entitlement(self,**kwargs):
   authority.create_external_entitlement(**kwargs);service.admin_transition(order['order_id'],'refund');raise RuntimeError('lost')
  def read_external_entitlement_acknowledgement(self,**kwargs):
   self.reads+=1
   if self.reads==1:raise RuntimeError('temporary')
   return authority.read_external_entitlement_acknowledgement(**kwargs)
 loss=Loss()
 with pytest.raises(RuntimeError,match='reconciliation_pending'):service.deliver_entitlement(order['order_id'],loss)
 with service._db() as db:
  row=db.execute('select state,reconciliation_phase from entitlement_outbox').fetchone();assert tuple(row)==('quarantined','readback_only');db.execute("update entitlement_outbox set next_attempt_at='2000-01-01T00:00:00+00:00'");service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 restart=PaymentService(service.config);restart.deliver_entitlement(order['order_id'],loss)
 with restart._db() as db:assert db.execute('select count(*) from revocation_outbox').fetchone()[0]==1 and db.execute('select license_id from entitlement_outbox').fetchone()[0]
 restart.deliver_revocation(order['order_id'],authority)
 with authority._connect() as db:assert db.execute('select revoked_at from licenses').fetchone()[0] is not None

def test_reconciliation_phase_transition_forgery_is_blocked(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);paid(service)
 with service._db() as db:
  with pytest.raises(__import__('sqlite3').IntegrityError,match='phase'):db.execute("update entitlement_outbox set reconciliation_phase='readback_only'")

def test_expired_authorized_ack_restart_is_readback_only_and_refund_compensates(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);row=service.claim_outbox('crashed',lease_seconds=-1,order_id=order['order_id'])
 with service._db() as db:
  db.execute("update entitlement_outbox set reconciliation_phase='crossing_prepared' where order_id=?",(order['order_id'],));db.execute("update entitlement_outbox set reconciliation_phase='crossing_authorized' where order_id=?",(order['order_id'],));service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 digest=service._outbox_payload_digest(row);authority.create_external_entitlement(source=row['source'],source_id=row['source_id'],payload_digest=digest,authority_id=service.config.authority_id,signer_identity=authority.handshake(),major_version=1,seat_limit=2);service.admin_transition(order['order_id'],'refund')
 class ReadbackOnly:
  creates=0
  def handshake(self):return authority.handshake()
  def create_external_entitlement(self,**kwargs):self.creates+=1;raise AssertionError('create forbidden')
  def read_external_entitlement_acknowledgement(self,**kwargs):return authority.read_external_entitlement_acknowledgement(**kwargs)
 proxy=ReadbackOnly();restart=PaymentService(service.config)
 with restart._db() as db:db.execute("update entitlement_outbox set next_attempt_at='2000-01-01T00:00:00+00:00'");restart._write_checkpoint_document(restart._checkpoint_document(db));db.commit()
 claimed=restart.claim_outbox('new',order_id=order['order_id']);assert claimed['reconciliation_phase']=='readback_only';restart.deliver_claimed_outbox(claimed,proxy,'new');assert proxy.creates==0
 with restart._db() as db:assert db.execute('select count(*) from revocation_outbox').fetchone()[0]==1
 restart.deliver_revocation(order['order_id'],authority)
 with authority._connect() as db:assert db.execute('select revoked_at from licenses').fetchone()[0] is not None

def test_prepared_lease_fields_are_individually_immutable(tmp_path):
 import sqlite3
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.claim_outbox('owner',order_id=order['order_id'])
 with service._db() as db:db.execute("update entitlement_outbox set reconciliation_phase='crossing_prepared'");service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 for clause in ("lease_owner='attacker'","fencing_version=fencing_version+1","state='pending'","lease_expires_at='2099-01-01T00:00:00+00:00'"):
  with service._db() as db:
   with pytest.raises(sqlite3.IntegrityError,match='prepared crossing lease'):db.execute(f'update entitlement_outbox set {clause}')
 with service._db() as db:assert tuple(db.execute('select lease_owner,reconciliation_phase from entitlement_outbox').fetchone())==('owner','crossing_prepared')

def test_admin_reconciliation_license_projection_requires_valid_signature(tmp_path):
 import sqlite3
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.deliver_entitlement(order['order_id'],authority)
 valid=service.list_authority_reconciliation();assert valid[0]['evidence_status']=='verified' and valid[0]['license_id']
 for column,value in [('authority_ack_signature','short'),('authority_ack_signature','!'*88),('delivery_receipt','0'*64),('source_id','0'*64),('authority_key_id','wrong')]:
  clone=tmp_path/f'projection-{column}-{len(value)}.sqlite'
  with service._db() as source,sqlite3.connect(clone) as destination:source.backup(destination)
  checkpoint=tmp_path/f'projection-{column}-{len(value)}.checkpoint';checkpoint.write_bytes(service.config.settlement_checkpoint_path.read_bytes());copy=PaymentService(replace(service.config,db_path=clone,settlement_checkpoint_path=checkpoint))
  with copy._db() as db:
   for trigger in ('entitlement_outbox_authority_ack_once','entitlement_outbox_ack_once','entitlement_outbox_payload_immutable','entitlement_outbox_authority_identity_immutable','entitlement_outbox_delivered_ack_required'):db.execute(f'drop trigger if exists {trigger}')
   db.execute(f'update entitlement_outbox set {column}=?',(value,));copy._write_checkpoint_document(copy._checkpoint_document(db));db.commit()
  projected=copy.list_authority_reconciliation()[0];assert projected['license_id'] is None and projected['evidence_status']=='unavailable'

def test_expired_prepared_restart_resets_then_creates_exactly_once(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.claim_outbox('dead',lease_seconds=-1,order_id=order['order_id'])
 with service._db() as db:db.execute("update entitlement_outbox set reconciliation_phase='crossing_prepared'");service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 class Count:
  creates=0
  def handshake(self):return authority.handshake()
  def create_external_entitlement(self,**kwargs):self.creates+=1;return authority.create_external_entitlement(**kwargs)
  def read_external_entitlement_acknowledgement(self,**kwargs):return authority.read_external_entitlement_acknowledgement(**kwargs)
 proxy=Count();restart=PaymentService(service.config);result=restart.deliver_entitlement(order['order_id'],proxy);assert result['license_id'] and proxy.creates==1

def test_expired_prepared_refund_cancels_without_create_and_evidence_blocks_reset(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.claim_outbox('dead',lease_seconds=-1,order_id=order['order_id'])
 with service._db() as db:db.execute("update entitlement_outbox set reconciliation_phase='crossing_prepared'");service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 service.admin_transition(order['order_id'],'refund');assert PaymentService(service.config).claim_outbox('new',order_id=order['order_id']) is None
 with service._db() as db:assert tuple(db.execute('select state,reconciliation_phase from entitlement_outbox').fetchone())==('quarantined','none')

@pytest.mark.parametrize('bad',['0','',' ','2000-01-01T00:00:00','2000-01-01T00:00:00Z','2000-01-01T08:00:00+08:00','2000-99-99T00:00:00+00:00','2000-01-01T00:00:00+00:00junk'])
@pytest.mark.parametrize('phase',['crossing_prepared','crossing_authorized'])
def test_malformed_entitlement_lease_expiry_never_authorizes_reclaim(tmp_path,bad,phase):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);claimed=service.claim_outbox('owner',order_id=order['order_id'])
 with service._db() as db:
  db.execute('update entitlement_outbox set lease_expires_at=?',(bad,));db.execute("update entitlement_outbox set reconciliation_phase='crossing_prepared'")
  if phase=='crossing_authorized':db.execute("update entitlement_outbox set reconciliation_phase='crossing_authorized'")
  service._write_checkpoint_document(service._checkpoint_document(db));db.commit()
 restart=PaymentService(service.config);before=service.config.settlement_checkpoint_path.read_bytes()
 with pytest.raises(RuntimeError,match='invalid outbox lease timestamp'):restart.claim_outbox('attacker',order_id=order['order_id'])
 assert service.config.settlement_checkpoint_path.read_bytes()==before
 with service._db() as db:assert tuple(db.execute('select state,lease_owner,fencing_version,reconciliation_phase from entitlement_outbox').fetchone())==('leased','owner',claimed['fencing_version'],phase)

def test_canonical_entitlement_lease_expiry_past_and_future(tmp_path):
 k,p,d=signer_setup();authority=make_authority(tmp_path/'authority.sqlite',k,p,d,OfflineFixtureMonotonicAnchor());service=configured(tmp_path/'payments.sqlite',authority);order=paid(service);service.claim_outbox('old',lease_seconds=-1,order_id=order['order_id']);assert service.claim_outbox('new',order_id=order['order_id'])['lease_owner']=='new'
