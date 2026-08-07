import os, subprocess, sys, textwrap

def test_token_and_free_seats_archive_restore_export(tmp_path):
    script = r'''
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer test-session-token'}
with TestClient(app) as client:
 assert client.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'}).status_code==200
 assert client.get('/api/health/deep').status_code==401
 assert client.get('/api/health/deep',headers=h).status_code==200
 p=client.post('/api/projects',headers=h,json={'name':'one'}).json()
 assert client.post('/api/projects',headers=h,json={'name':'two'}).status_code==402
 assert client.patch(f"/api/projects/{p['id']}",headers=h,json={'status':'archived','expected_project_revision':p['revision']}).status_code==200
 replacement=client.post('/api/projects',headers=h,json={'name':'two'});assert replacement.status_code==201
 assert client.get(f"/api/projects/{p['id']}",headers=h).status_code==200
 assert client.get(f"/api/projects/{p['id']}/export-json",headers=h).status_code==200
 assert client.patch(f"/api/projects/{p['id']}",headers=h,json={'status':'active','expected_project_revision':p['revision']+1}).status_code==409
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'test.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0, result.stdout+result.stderr
