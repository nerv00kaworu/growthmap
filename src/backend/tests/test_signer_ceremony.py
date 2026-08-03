import base64, concurrent.futures, hashlib, sqlite3
from datetime import datetime, timedelta, timezone
from enum import IntEnum
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from licensing.authority import LicenseAuthority, activation_challenge
from licensing.signer_ceremony import DOMAIN, PURPOSE, OfflineFixtureMonotonicAnchor, validate, validate_anchor_claim

NOW=datetime(2026,8,2,tzinfo=timezone.utc)
class Signer:
 def __init__(self,key):self.key=key;self.mode="ok"
 def sign(self,message):
  if self.mode=="throw":raise Exception("provider SECRET_MARKER diagnostic")
  if self.mode=="short":return b"x"*63
  if self.mode=="wrong":return Ed25519PrivateKey.generate().sign(message)
  return self.key.sign(message)

class ThrowingAnchor:
 def read(self):raise Exception("anchor SECRET_MARKER read")
 def compare_and_advance(self,expected,new):raise Exception("anchor SECRET_MARKER claim")

def assert_sanitized(error):
 seen=set();pending=[error]
 while pending:
  current=pending.pop()
  if current is None or id(current) in seen:continue
  seen.add(id(current));text=str(current)+repr(current)
  assert "SECRET_MARKER" not in text
  pending.extend([current.__cause__,current.__context__])

def setup(generation=1,key=None,**changes):
 key=key or Ed25519PrivateKey.generate();public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 d={"schema_version":1,"purpose":PURPOSE,"domain":DOMAIN,"algorithm":"Ed25519","authority_id":"growthmap-authority-primary","key_id":f"issuer-{generation}","generation":generation,"activated_at":"2026-08-02T00:00:00Z","predecessor_generation":None if generation==1 else generation-1,"public_key_sha256":hashlib.sha256(public).hexdigest(),"provider_attestation_id":f"kms:review-{generation}"};d.update(changes)
 return key,public,d

def authority(path,key,public,d,anchor):return LicenseAuthority.from_external_signer(path,signer=Signer(key),ceremony_descriptor=d,reviewed_public_key=public,generation_anchor=anchor,now=lambda:NOW)

def test_happy_reopen_rotation_rollback_and_same_generation_mismatch(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup();a=authority(db,k,p,d,anchor);assert a.handshake()["generation"]==1
 authority(db,k,p,d,anchor)
 k2,p2,d2=setup(2);authority(db,k2,p2,d2,anchor)
 with pytest.raises(RuntimeError):authority(db,k,p,d,anchor)
 bad=dict(d2,key_id="other-key")
 with pytest.raises(RuntimeError):authority(db,k2,p2,bad,anchor)

def test_anchor_unavailable_conflict_and_public_hash(tmp_path):
 k,p,d=setup();anchor=OfflineFixtureMonotonicAnchor();anchor.available=False
 with pytest.raises(RuntimeError,match="anchor") as unavailable:authority(tmp_path/"a.db",k,p,d,anchor)
 assert_sanitized(unavailable.value)
 with pytest.raises(RuntimeError,match="anchor") as conflict:authority(tmp_path/"b.db",k,p,d,OfflineFixtureMonotonicAnchor(2,"0"*64))
 assert_sanitized(conflict.value)
 with pytest.raises(RuntimeError,match="anchor") as throwing:authority(tmp_path/"c.db",k,p,d,ThrowingAnchor())
 assert_sanitized(throwing.value)
 with pytest.raises(ValueError,match="hash"):validate(d,p+b"x",NOW)

def test_strict_schema_types_utc_future_and_predecessor():
 k,p,d=setup()
 cases=[dict(d,extra=1),dict(d,generation=True),dict(d,activated_at="2026-08-02T00:00:00+00:00"),dict(d,activated_at="2026-08-03T00:00:00Z")]
 for bad in cases:
  with pytest.raises(ValueError):validate(bad,p,NOW)
 k2,p2,d2=setup(2,predecessor_generation=True)
 with pytest.raises(ValueError):validate(d2,p2,NOW)

def test_provider_failures_are_generic_and_not_persisted(tmp_path):
 k,p,d=setup();a=authority(tmp_path/"a.db",k,p,d,OfflineFixtureMonotonicAnchor());a.create_license(license_id="license-signer");device=Ed25519PrivateKey.generate();pub=base64.b64encode(device.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();nonce="nonce_0123456789abcdef";proof=base64.b64encode(device.sign(activation_challenge("license-signer",pub,nonce))).decode()
 for mode,error in [("throw","license_signing_unavailable"),("short","license_signing_failed"),("wrong","license_signing_failed")]:
  a.signer.mode=mode
  with pytest.raises(RuntimeError,match=error) as caught:a.activate(license_id="license-signer",device_public_key=pub,nonce=nonce,proof=proof)
  assert_sanitized(caught.value)
 with sqlite3.connect(tmp_path/"a.db") as db:assert "SECRET_MARKER" not in " ".join(str(x) for row in db.execute("select * from signer_ceremonies") for x in row)


def test_handshake_fails_closed_for_old_instance_and_unavailable_anchor(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup();old=authority(db,k,p,d,anchor)
 assert old.handshake()["authority_id"]=="growthmap-authority-primary"
 k2,p2,d2=setup(2);current=authority(db,k2,p2,d2,anchor);assert current.handshake()["generation"]==2
 with pytest.raises(RuntimeError,match="signer_state_conflict"):old.handshake()
 anchor.available=False
 with pytest.raises(RuntimeError,match="signer_state_unavailable") as caught:current.handshake()
 assert_sanitized(caught.value)


def test_anchor_advanced_then_db_pin_failure_requires_quarantine(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup();old=authority(db,k,p,d,anchor)
 with sqlite3.connect(db) as conn:
  conn.execute("CREATE TRIGGER block_signer_rotation BEFORE INSERT ON signer_ceremonies WHEN NEW.generation=2 BEGIN SELECT RAISE(ABORT,'fixture pin failure'); END")
 k2,p2,d2=setup(2)
 with pytest.raises(sqlite3.DatabaseError,match="fixture pin failure"):authority(db,k2,p2,d2,anchor)
 assert anchor.read()["generation"]==2
 with sqlite3.connect(db) as conn:assert conn.execute("SELECT max(generation) FROM signer_ceremonies").fetchone()[0]==1
 with pytest.raises(RuntimeError,match="signer_state_conflict"):old.handshake()
 # Remove the deterministic fixture fault: the exact already-claimed descriptor
 # recovers forward, while another descriptor/key at generation 2 can never claim.
 with sqlite3.connect(db) as conn:conn.execute("DROP TRIGGER block_signer_rotation")
 bad_key,bad_public,bad_descriptor=setup(2)
 with pytest.raises(RuntimeError,match="anchor"):authority(db,bad_key,bad_public,bad_descriptor,anchor)
 recovered=authority(db,k2,p2,d2,anchor);assert recovered.handshake()["generation"]==2


def test_anchor_claim_strict_shape_types_and_wrong_digest(tmp_path):
 class Number(IntEnum):ONE=1
 class EqualOne:
  def __eq__(self,other):return other==1
 digest="a"*64
 malformed=[1,(1,digest),[1,digest],{"generation":1},{"generation":1,"ceremony_sha256":digest,"extra":1},{"generation":True,"ceremony_sha256":digest},{"generation":1.0,"ceremony_sha256":digest},{"generation":Number.ONE,"ceremony_sha256":digest},{"generation":EqualOne(),"ceremony_sha256":digest},{"generation":1,"ceremony_sha256":"A"*64}]
 for claim in malformed:
  with pytest.raises(ValueError):validate_anchor_claim(claim,allow_zero=False)
 k,p,d=setup();good=authority(tmp_path/"wrong.db",k,p,d,OfflineFixtureMonotonicAnchor())
 good.anchor._claim={"generation":1,"ceremony_sha256":"0"*64}
 with pytest.raises(RuntimeError,match="signer_state_conflict"):good.handshake()


def test_external_anchor_return_shape_and_type_rejected(tmp_path):
 class EqualOne:
  def __eq__(self,other):return other==1
 class Number(IntEnum):ONE=1
 class BadReturnAnchor:
  def __init__(self,value):self.value=value
  def compare_and_advance(self,expected,new):return self.value
  def read(self):return self.value
 k,p,d=setup()
 values=[1,1.0,True,{"generation":1.0,"ceremony_sha256":"0"*64},{"generation":Number.ONE,"ceremony_sha256":"0"*64},{"generation":EqualOne(),"ceremony_sha256":"0"*64},{"generation":1,"ceremony_sha256":"0"*64,"extra":1}]
 for index,value in enumerate(values):
  # Stable numeric names avoid Windows-invalid characters from str(type(value)).
  with pytest.raises(RuntimeError,match="anchor"):authority(tmp_path/f"bad-anchor-{index}.db",k,p,d,BadReturnAnchor(value))


def test_concurrent_competing_descriptors_exactly_one_anchor_winner(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup();authority(db,k,p,d,anchor)
 winner=setup(2);competitor=setup(2);candidates=[winner]*12+[competitor]*12
 def rotate(candidate):
  try:return authority(db,*candidate,anchor)
  except RuntimeError:return None
 with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:results=list(pool.map(rotate,candidates))
 successful=[a for a in results if a is not None];assert successful
 identities={(a.handshake()["key_id"],a.handshake()["public_key_sha256"]) for a in successful};assert len(identities)==1
 # Every constructor for the winning exact descriptor safely reopens; every
 # competing descriptor loses generically rather than surfacing sqlite BUSY.
 winner_identity=(winner[2]["key_id"],winner[2]["public_key_sha256"])
 expected_successes=12 if next(iter(identities))==winner_identity else 12
 assert len(successful)==expected_successes
 claim=anchor.read()
 with sqlite3.connect(db) as conn:
  descriptor=conn.execute("SELECT descriptor_json FROM signer_ceremonies WHERE generation=2").fetchone()[0]
 assert claim=={"generation":2,"ceremony_sha256":hashlib.sha256(descriptor.encode()).hexdigest()}


def test_concurrent_initial_same_descriptor_bootstrap_is_stable(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup()
 with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:instances=list(pool.map(lambda _:authority(db,k,p,d,anchor),range(48)))
 assert all(a.handshake()["generation"]==1 for a in instances)
 with sqlite3.connect(db) as conn:
  assert conn.execute("select count(*) from signer_ceremonies").fetchone()[0]==1


def test_concurrent_construction_and_append_only_triggers(tmp_path):
 db=tmp_path/"a.db";anchor=OfflineFixtureMonotonicAnchor();k,p,d=setup()
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda _:authority(db,k,p,d,anchor),range(6)))
 with sqlite3.connect(db) as conn:
  assert conn.execute("select count(*) from signer_ceremonies").fetchone()[0]==1
  with pytest.raises(sqlite3.DatabaseError):conn.execute("update signer_ceremonies set key_id='changed'")
  with pytest.raises(sqlite3.DatabaseError):conn.execute("delete from signer_ceremonies")
