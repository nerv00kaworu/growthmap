import base64, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from desktop.entitlements import canonical_payload, initialize_trial, trial_entitlement, verify_document

def signed(private, **changes):
    doc={"schema_version":1,"edition":"personal","license_id":"TEST-ONLY-1","major_version":1,"device_allowance":2,"issued_at":"2026-01-01T00:00:00+00:00","expires_at":None,"revoked_at":None,"max_active_projects":None,"next_check_in_at":"2099-02-01T00:00:00+00:00"}
    doc.update(changes);doc["signature"]=base64.b64encode(private.sign(canonical_payload(doc))).decode();return doc

def test_entitlement_peek_is_side_effect_free(tmp_path):
 start=datetime(2026,1,1,tzinfo=timezone.utc);p=tmp_path/'trial.json';initialize_trial(p,now=start);before=p.read_bytes()
 assert trial_entitlement(p,now=start+timedelta(hours=1)).state=='trial'
 assert p.read_bytes()==before
 trial_entitlement(p,now=start+timedelta(hours=1),checkpoint=True);assert p.read_bytes()!=before

def test_trial_boundaries_rollback_and_corruption(tmp_path):
    start=datetime(2026,1,1,tzinfo=timezone.utc);p=tmp_path/'trial.json';initialize_trial(p,now=start)
    assert trial_entitlement(p,now=start).state=='trial'
    assert trial_entitlement(p,now=start+timedelta(days=6,hours=23)).mutations_allowed
    assert trial_entitlement(p,now=start+timedelta(days=7)).reason=='trial_expired'
    assert trial_entitlement(p,now=start-timedelta(minutes=6)).reason=='clock_rollback'
    p.write_text('{bad');assert trial_entitlement(p,now=start).reason=='corrupt_trial_state'
    initialize_trial(p,now=start+timedelta(days=100));assert p.read_text()=='{bad'

def test_trial_requires_explicit_successful_start(tmp_path):
    code=r'''from fastapi.testclient import TestClient
from main import app
from pathlib import Path
p=Path(r"PATH")
with TestClient(app) as c:
 assert not p.exists()
 assert c.post('/api/desktop/trial/start',headers={'Authorization':'Bearer t','X-GrowthMap-Fresh-Install':'1'},json={'started_at':'2026-01-01T00:00:00+00:00','installation_id':'test-installation'}).status_code==200
 assert p.exists()
'''.replace('PATH',str(tmp_path/'explicit.json'))
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'t','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'00ea2c7a12956fa4fff2f382fa32b3bafd333082d7f6765f1ad6edb5741b9218','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'explicit.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'explicit.json')}
    result=subprocess.run([sys.executable,'-c',code],env=env,cwd=Path(__file__).parents[1],text=True,capture_output=True);assert result.returncode==0,result.stdout+result.stderr

def test_license_major_signature_and_device_schema(tmp_path):
    private=Ed25519PrivateKey.generate();pub=tmp_path/'pub.pem';pub.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    assert verify_document(signed(private),pub,now=datetime(2026,1,2,tzinfo=timezone.utc)).state=='paid'
    assert verify_document(signed(private,major_version=2),pub,current_major=1).reason=='major_mismatch'
    bad=signed(private);bad['device_allowance']=3;assert verify_document(bad,pub).reason=='invalid_signature'
    assert verify_document(signed(private,device_allowance=0),pub).reason=='invalid_device_allowance'
    assert verify_document(signed(private,device_binding='other-device-123'),pub).reason=='device_binding_unsupported'

def test_major_mismatch_import_cannot_replace_valid_persisted_license(tmp_path):
    private=Ed25519PrivateKey.generate();pub=tmp_path/'pub.pem';pub.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo));license_file=tmp_path/'license.json';license_file.write_text(json.dumps(signed(private)))
    code=r'''import json
from fastapi.testclient import TestClient
from main import app
p=r"LICENSE";before=open(p).read();wrong=json.load(open(r"WRONG"))
with TestClient(app) as c:
 assert c.get('/api/desktop/entitlement',headers={'Authorization':'Bearer t'}).json()['state']=='paid'
 assert c.post('/api/desktop/license/import',headers={'Authorization':'Bearer t'},json={'document':wrong}).status_code==400
 assert open(p).read()==before
'''.replace('LICENSE',str(license_file)).replace('WRONG',str(tmp_path/'wrong.json'))
    (tmp_path/'wrong.json').write_text(json.dumps(signed(private,major_version=2)))
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'t','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'00ea2c7a12956fa4fff2f382fa32b3bafd333082d7f6765f1ad6edb5741b9218','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'paid.db'}",'GROWTHMAP_LICENSE_FILE':str(license_file),'GROWTHMAP_LICENSE_PUBLIC_KEY':str(pub),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    result=subprocess.run([sys.executable,'-c',code],env=env,cwd=Path(__file__).parents[1],text=True,capture_output=True);assert result.returncode==0,result.stdout+result.stderr

def test_expired_route_matrix_and_authoring_unaffected(tmp_path):
    code=r'''from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer t'}
with TestClient(app) as c:
 assert c.get('/api/projects',headers=h).status_code==200
 mutations=[('post','/api/projects',{'name':'x'}),('post','/api/projects/import-json',{}),('patch','/api/projects/nope',{}),('delete','/api/projects/nope',None),('post','/api/projects/nope/nodes',{}),('patch','/api/nodes/nope',{}),('delete','/api/nodes/nope',None),('post','/api/edges',{}),('patch','/api/edges/nope',{}),('delete','/api/edges/nope',None),('post','/api/nodes/nope/blocks',{}),('patch','/api/blocks/nope',{}),('delete','/api/blocks/nope',None),('post','/api/agent-sessions',{}),('post','/api/agent-artifacts/nope/approve',{}),('post','/api/agent-artifacts/nope/reject',{}),('post','/api/ai/expand',{}),('post','/api/ai/deepen',{}),('post','/api/ai/chat',{}),('post','/api/projects/nope/branches',{}),('post','/api/branches/nope/merge',{}),('delete','/api/branches/nope',None),('post','/api/nodes/nope/move',{}),('post','/api/nodes/nope/reparent',{}),('post','/api/providers',{}),('put','/api/desktop/secrets/x',{'api_key':'x'})]
 for method,path,body in mutations:
  assert c.request(method.upper(),path,headers=h,json=body).status_code==403,(method,path)
 assert c.get('/api/desktop/entitlement',headers=h).status_code==200
 assert c.post('/api/desktop/license/import',headers=h,json={'document':{}}).status_code==400
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'t','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'00ea2c7a12956fa4fff2f382fa32b3bafd333082d7f6765f1ad6edb5741b9218','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'desktop.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    (tmp_path/'trial.json').write_text('{bad')
    result=subprocess.run([sys.executable,'-c',code],env=env,cwd=Path(__file__).parents[1],text=True,capture_output=True);assert result.returncode==0,result.stdout+result.stderr
    author=r'''from fastapi.testclient import TestClient
from main import app
with TestClient(app) as c: assert c.post('/api/projects',json={'name':'web'}).status_code==201
'''
    env2={**os.environ,'APP_ENV':'test','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'web.db'}"};env2.pop('GROWTHMAP_DESKTOP_MODE',None);env2.pop('GROWTHMAP_SESSION_TOKEN',None)
    result=subprocess.run([sys.executable,'-c',author],env=env2,cwd=Path(__file__).parents[1],text=True,capture_output=True);assert result.returncode==0,result.stdout+result.stderr

def test_entitlement_get_is_byte_and_mtime_stable_and_checkpoint_is_trial_only(tmp_path):
    trial=tmp_path/'trial.json';now=datetime.now(timezone.utc);initialize_trial(trial,now=now);code=r'''import os
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
p=Path(os.environ['GROWTHMAP_TRIAL_STATE_FILE']);before=(p.read_bytes(),p.stat().st_mtime_ns)
with TestClient(app) as c:
 h={'Authorization':'Bearer t'}
 assert c.get('/api/desktop/entitlement',headers=h).status_code==200
 assert (p.read_bytes(),p.stat().st_mtime_ns)==before
 assert c.post('/api/desktop/entitlement/checkpoint',headers=h).status_code==200
 assert p.read_bytes()!=before[0]
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_SESSION_TOKEN':'t','GROWTHMAP_STARTUP_VERDICT_MODE':'trial','GROWTHMAP_STARTUP_VERDICT_NONCE':'N'*43,'GROWTHMAP_TRIAL_STATE_FILE':str(trial),'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'get.db'}",'GROWTHMAP_SCHEMA_CURRENT':'1'}
    import hashlib,hmac;env['GROWTHMAP_STARTUP_VERDICT_MAC']=hmac.new(b't',f"growthmap-startup-v1:trial:{'N'*43}".encode(),hashlib.sha256).hexdigest()
    result=subprocess.run([sys.executable,'-c',code],env=env,cwd=Path(__file__).parents[1],text=True,capture_output=True);assert result.returncode==0,result.stdout+result.stderr

def test_old_v1_license_bootstraps_without_attacker_timestamp(tmp_path):
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 from cryptography.hazmat.primitives import serialization
 import base64,json
 from desktop.entitlements import verify_document
 key=Ed25519PrivateKey.generate();pub=tmp_path/'pub.pem';pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 d={"schema_version":1,"edition":"personal","license_id":"legacy-1","major_version":1,"device_allowance":2,"issued_at":"2000-01-01T00:00:00+00:00","expires_at":None,"revoked_at":None,"max_active_projects":None};d['signature']=base64.b64encode(key.sign(json.dumps(d,sort_keys=True,separators=(',',':')).encode())).decode()
 v=verify_document(d,pub,now=datetime(2099,1,1,tzinfo=timezone.utc));assert v.valid and v.reason=='legacy_bootstrap'

def test_revocation_assertion_strict_types_canonical_time_and_future(tmp_path):
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 from cryptography.hazmat.primitives import serialization
 import base64,json,pytest
 from desktop.entitlements import verify_revocation_assertion,REVOCATION_DOMAIN
 key=Ed25519PrivateKey.generate();pub=tmp_path/'pub.pem';pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 base={"schema_version":1,"assertion_type":"growthmap_license_revocation","product":"growthmap","major_version":1,"license_id":"legacy-1","revoked_at":"2026-01-01T00:00:00.000000Z","sequence":1,"reason_code":None}
 def signed(**change):
  d={**base,**change};d['signature']=base64.b64encode(key.sign(REVOCATION_DOMAIN+json.dumps(d,sort_keys=True,separators=(',',':')).encode())).decode();return d
 now=datetime(2026,1,1,tzinfo=timezone.utc);assert verify_revocation_assertion(signed(),'legacy-1',pub,now=now)
 for bad in [signed(schema_version=True),signed(major_version=True),signed(revoked_at='2026-01-01T00:00:00+00:00'),signed(revoked_at='2026-01-01T08:00:00+08:00'),signed(revoked_at='2026-01-01T00:06:00.000000Z')]:
  with pytest.raises(Exception):verify_revocation_assertion(bad,'legacy-1',pub,now=now)

def test_strict_json_rejects_duplicate_and_case_collision():
 import pytest
 from desktop.entitlements import strict_json_loads
 for raw in ['{"product":"evil","product":"growthmap"}','{"license_id":"x","LICENSE_ID":"x"}']:
  with pytest.raises(ValueError):strict_json_loads(raw)
