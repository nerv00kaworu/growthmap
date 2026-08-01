import base64, concurrent.futures
from datetime import datetime, timezone
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from licensing.authority import LicenseAuthority, activation_challenge, device_identifier
from desktop.entitlements import verify_document

def keyfile(tmp_path):
 k=Ed25519PrivateKey.generate();p=tmp_path/'issuer.pem';p.write_bytes(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));pub=tmp_path/'pub.pem';pub.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo));return p,pub

def device():
 k=Ed25519PrivateKey.generate();public=base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();return k,public

def activate(a,license_id,d,n='nonce_0123456789abcdef'):
 k,pub=d;proof=base64.b64encode(k.sign(activation_challenge(license_id,pub,n))).decode();return a.activate(license_id=license_id,device_public_key=pub,nonce=n,proof=proof)

def test_two_seats_idempotency_response_recovery_wrong_device_and_deactivate(tmp_path):
 private,pub=keyfile(tmp_path);a=LicenseAuthority(tmp_path/'ledger.db',private,now=lambda:datetime(2026,1,1,tzinfo=timezone.utc));a.create_license(license_id='license-1');d1,d2,d3=device(),device(),device()
 c1=activate(a,'license-1',d1);assert activate(a,'license-1',d1)==c1 # response loss retry gets byte-equivalent document
 c2=activate(a,'license-1',d2);assert c1['activation_id']!=c2['activation_id']
 with pytest.raises(ValueError,match='seat_limit'):activate(a,'license-1',d3)
 assert verify_document(c1,pub,device_public_key=d1[1],now=datetime(2026,1,1,tzinfo=timezone.utc)).mutations_allowed
 assert verify_document(c1,pub,device_public_key=d2[1],now=datetime(2026,1,1,tzinfo=timezone.utc)).reason=='wrong_device'
 assert a.deactivate(license_id='license-1',device_id=device_identifier(d1[1]));assert activate(a,'license-1',d3)['device_id']==device_identifier(d3[1])

def test_concurrent_activation_never_exceeds_two(tmp_path):
 private,_=keyfile(tmp_path);a=LicenseAuthority(tmp_path/'ledger.db',private);a.create_license(license_id='license-2');devices=[device() for _ in range(8)]
 def call(d):
  try: activate(a,'license-2',d);return True
  except ValueError:return False
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(call,devices))
 assert sum(results)==2

def test_private_key_is_required_and_proof_is_required(tmp_path):
 with pytest.raises(RuntimeError):LicenseAuthority(tmp_path/'x.db',None)
 private,_=keyfile(tmp_path);a=LicenseAuthority(tmp_path/'x.db',private);a.create_license(license_id='license-3');_,pub=device()
 with pytest.raises(ValueError,match='proof'):a.activate(license_id='license-3',device_public_key=pub,nonce='nonce_0123456789abcdef',proof=base64.b64encode(b'x'*64).decode())


def test_check_in_expired_and_raw_certificate_persists_across_reopen(tmp_path):
 private,pub=keyfile(tmp_path);clock=lambda:datetime(2026,1,1,tzinfo=timezone.utc);a=LicenseAuthority(tmp_path/'ledger.db',private,now=clock);a.create_license(license_id='license-raw');d=device();cert=activate(a,'license-raw',d)
 import sqlite3
 with sqlite3.connect(tmp_path/'ledger.db') as db:raw1=db.execute("select certificate_json from activations").fetchone()[0]
 assert verify_document(cert,pub,device_public_key=d[1],now=datetime(2026,2,2,tzinfo=timezone.utc)).reason=='check_in_required'
 a2=LicenseAuthority(tmp_path/'ledger.db',private,now=clock);assert activate(a2,'license-raw',d)==cert
 with sqlite3.connect(tmp_path/'ledger.db') as db:raw2=db.execute("select certificate_json from activations").fetchone()[0]
 assert raw1.encode()==raw2.encode()

def test_append_only_request_ledger_rejects_a_after_b_and_reopen(tmp_path):
 private,_=keyfile(tmp_path);db=tmp_path/'ledger.db';a=LicenseAuthority(db,private);a.create_license(license_id='license-history');d=device()
 ca=activate(a,'license-history',d,'nonce_A_0123456789abcdef');a.deactivate(license_id='license-history',device_id=device_identifier(d[1]))
 cb=activate(a,'license-history',d,'nonce_B_0123456789abcdef');assert cb!=ca;a.deactivate(license_id='license-history',device_id=device_identifier(d[1]))
 reopened=LicenseAuthority(db,private)
 with pytest.raises(ValueError,match='activation_nonce_consumed'):activate(reopened,'license-history',d,'nonce_A_0123456789abcdef')
 with pytest.raises(ValueError,match='activation_nonce_consumed'):activate(reopened,'license-history',d,'nonce_B_0123456789abcdef')
 import sqlite3
 with sqlite3.connect(db) as conn:assert conn.execute("select count(*) from activation_requests").fetchone()[0]==2
