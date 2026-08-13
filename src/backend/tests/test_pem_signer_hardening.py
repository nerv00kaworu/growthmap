import hashlib, os
from datetime import datetime, timezone
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from licensing.authority import LicenseAuthority
from licensing.pem_signer import canonical,load_ed25519_private_key,validate_ceremony_record,validate_descriptor
from licensing.signer_ceremony import OfflineFixtureMonotonicAnchor

NOW="2026-08-08T08:00:00Z"; H="1"*64

def material(tmp_path):
 key=Ed25519PrivateKey.generate();pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption());public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo);path=tmp_path/"signer.pem";path.write_bytes(pem);path.chmod(0o400);return key,path,pem,public

def fixtures(pem,public,generation=1,predecessor=None):
 reviewers={};private={}
 for rid,role in (("reviewer-one","security-reviewer"),("reviewer-two","release-reviewer")):
  k=Ed25519PrivateKey.generate();p=k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo);d=k.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo);private[rid]=k;reviewers[rid]={"role":role,"public_key_pem":p.decode(),"public_spki_der_sha256":hashlib.sha256(d).hexdigest()}
 pub=serialization.load_pem_public_key(public);der=pub.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
 body={"authority_id":"growthmap-authority-primary","key_id":"authority-key-001","generation":generation,"predecessor_generation":predecessor,"predecessor_ceremony_sha256":None if generation==1 else "2"*64,"public_pem_sha256":hashlib.sha256(public).hexdigest(),"public_spki_der_sha256":hashlib.sha256(der).hexdigest(),"private_pem_sha256":hashlib.sha256(pem).hexdigest(),"ceremony_at":NOW,"activated_at":NOW,"release_sha256":H,"deployment_config_sha256":"3"*64,"witness":{"reference":"witness-record-001","version":"version-001","digest":"4"*64},"change_id":"change-001","status":"active"}
 msg=b"growthmap-pem-ceremony-v2\0"+canonical(body);acks=[{"reviewer_id":rid,"signature":private[rid].sign(msg).hex()} for rid in private];record={"schema_version":1,"record":body,"acknowledgements":acks};descriptor={"schema_version":2,**body,"ceremony_record_sha256":hashlib.sha256(canonical(record)).hexdigest()};return record,descriptor,reviewers,private

@pytest.mark.parametrize(("ceremony","activation","valid"),[("2026-08-08T08:00:00.999999Z","2026-08-08T08:00:00Z",False),("2026-08-08T08:00:00Z","2026-08-08T08:00:00.000001Z",True),("2026-08-08T08:00:00Z","2026-08-08T08:00:00Z",True)])
def test_timestamp_datetime_ordering(ceremony,activation,valid,tmp_path):
 _,_,pem,public=material(tmp_path);record,_,roster,keys=fixtures(pem,public);body=record["record"];body["ceremony_at"]=ceremony;body["activated_at"]=activation;msg=b"growthmap-pem-ceremony-v2\0"+canonical(body);record["acknowledgements"]=[{"reviewer_id":rid,"signature":keys[rid].sign(msg).hex()} for rid in keys]
 if valid:assert validate_ceremony_record(record,roster)[0]==body
 else:
  with pytest.raises(RuntimeError):validate_ceremony_record(record,roster)

def test_stable_read_complete_binding_and_hardened_bridge(tmp_path):
 _,path,pem,public=material(tmp_path);record,d,roster,_=fixtures(pem,public);loaded=load_ed25519_private_key(path,expected_uid=os.getuid());assert validate_descriptor(d,record,loaded,public,authority_id=d["authority_id"],authorized_reviewers=roster)==d
 a=LicenseAuthority.from_hardened_pem(tmp_path/"a.db",private_key_file=path,expected_uid=os.getuid(),signer_descriptor=d,ceremony_record=record,reviewed_public_key=public,authorized_reviewers=roster,generation_anchor=OfflineFixtureMonotonicAnchor(),authority_id=d["authority_id"])
 assert a.handshake()["attestation"]=="pem-witness:"+d["ceremony_record_sha256"] and a.ceremony["activated_at"]==NOW

@pytest.mark.parametrize("mode",[0,0o200,0o440,0o600,0o640,0o644,0o404])
def test_exact_mode(mode,tmp_path):
 _,path,_,_=material(tmp_path);path.chmod(mode)
 with pytest.raises(RuntimeError):load_ed25519_private_key(path,expected_uid=os.getuid())

@pytest.mark.parametrize("mode",[0o720,0o702,0o777])
def test_parent_policy(mode,tmp_path):
 _,path,_,_=material(tmp_path);tmp_path.chmod(mode)
 with pytest.raises(RuntimeError,match="parent_permissions"):load_ed25519_private_key(path,expected_uid=os.getuid())

def test_relative_symlink_hardlink_fifo(tmp_path):
 _,path,_,_=material(tmp_path)
 with pytest.raises(RuntimeError,match="absolute"):load_ed25519_private_key("x",expected_uid=os.getuid())
 link=tmp_path/"l";link.symlink_to(path)
 with pytest.raises(RuntimeError):load_ed25519_private_key(link,expected_uid=os.getuid())
 hard=tmp_path/"h";os.link(path,hard)
 with pytest.raises(RuntimeError,match="link_count"):load_ed25519_private_key(path,expected_uid=os.getuid())
 os.unlink(hard);os.unlink(path);os.mkfifo(path,0o400)
 with pytest.raises(RuntimeError,match="not_regular"):load_ed25519_private_key(path,expected_uid=os.getuid())

def test_path_swap_same_size_rewrite_ctime_and_second_read(tmp_path):
 _,path,pem,_=material(tmp_path);replacement=tmp_path/"r";replacement.write_bytes(pem);replacement.chmod(0o400)
 def swap(stage,pfd,fd):
  if stage=="read":os.replace(replacement,path)
 with pytest.raises(RuntimeError,match="changed"):load_ed25519_private_key(path,expected_uid=os.getuid(),mutation_hook=swap)
 path.chmod(0o600);path.write_bytes(pem);path.chmod(0o400);old=os.stat(path).st_mtime_ns
 def rewrite(stage,pfd,fd):
  if stage=="read":
   path.chmod(0o600)
   with path.open("r+b") as writer:writer.seek(10);writer.write(b"A");writer.flush()
   path.chmod(0o400);os.utime(path,ns=(old,old))
 with pytest.raises(RuntimeError,match="changed"):load_ed25519_private_key(path,expected_uid=os.getuid(),mutation_hook=rewrite)

@pytest.mark.parametrize("variant",["large","multi","trailing","encrypted","rsa","placeholder"])
def test_bad_material(variant,tmp_path):
 key,path,pem,_=material(tmp_path)
 if variant=="large":data=b"X"*17000
 elif variant=="multi":data=pem+pem
 elif variant=="trailing":data=pem+b"x"
 elif variant=="encrypted":data=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(b"password"))
 elif variant=="rsa":data=generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
 else:data=b"-----BEGIN PRIVATE KEY-----\nPLACEHOLDER\n-----END PRIVATE KEY-----\n"
 path.chmod(0o600);path.write_bytes(data);path.chmod(0o400)
 with pytest.raises(RuntimeError):load_ed25519_private_key(path,expected_uid=os.getuid())

def test_owner_and_policy_required(tmp_path):
 _,path,_,_=material(tmp_path)
 with pytest.raises(RuntimeError,match="expected_uid"):load_ed25519_private_key(path)
 with pytest.raises(RuntimeError,match="owner|ancestor"):load_ed25519_private_key(path,expected_uid=os.getuid()+1)

@pytest.mark.parametrize("case",["unknown","duplicate","bad_signature","extra","embedded_key","alias_key","malformed_roster"])
def test_authorized_reviewers_fail_closed(case,tmp_path):
 _,_,pem,public=material(tmp_path);record,d,roster,keys=fixtures(pem,public)
 if case=="unknown":record["acknowledgements"][1]["reviewer_id"]="unknown-reviewer"
 elif case=="duplicate":record["acknowledgements"][1]=dict(record["acknowledgements"][0])
 elif case=="bad_signature":record["acknowledgements"][0]["signature"]="0"*128
 elif case=="extra":record["acknowledgements"][0]["public_key"]="self-provided"
 elif case=="embedded_key":record["acknowledgements"][0]["public_key"]="wrong"
 elif case=="alias_key":roster["reviewer-two"]={**roster["reviewer-one"],"role":"release-reviewer"}
 else:roster["reviewer-one"]["unexpected"]=1
 with pytest.raises(RuntimeError):validate_ceremony_record(record,roster)

@pytest.mark.parametrize("field",["authority_id","generation","predecessor_generation","predecessor_ceremony_sha256","public_pem_sha256","public_spki_der_sha256","private_pem_sha256","ceremony_at","activated_at","release_sha256","deployment_config_sha256","witness","change_id","status","ceremony_record_sha256"])
def test_descriptor_and_operational_binding(field,tmp_path):
 _,path,pem,public=material(tmp_path);record,d,roster,_=fixtures(pem,public);loaded=load_ed25519_private_key(path,expected_uid=os.getuid())
 if field=="authority_id":d[field]="other-authority"
 elif field in {"generation","predecessor_generation"}:d[field]=7
 elif field in {"ceremony_at","activated_at"}:d[field]="1970-not-time"
 elif field=="witness":d[field]={"reference":"x"}
 elif field in {"change_id","status"}:d[field]="X"
 else:d[field]="0"*64
 with pytest.raises(RuntimeError):validate_descriptor(d,record,loaded,public,authority_id="growthmap-authority-primary",authorized_reviewers=roster)
