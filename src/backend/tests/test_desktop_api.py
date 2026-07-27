import os, subprocess, sys, textwrap

def test_token_and_free_seats_archive_restore_export(tmp_path):
    script = r'''
from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer test-session-token'}
with TestClient(app) as client:
 assert client.get('/api/health/deep').status_code==401
 assert client.get('/api/health/deep',headers=h).status_code==200
 p=[client.post('/api/projects',headers=h,json={'name':n}).json() for n in ('one','two')]
 assert client.post('/api/projects',headers=h,json={'name':'three'}).status_code==402
 assert client.patch(f"/api/projects/{p[0]['id']}",headers=h,json={'status':'archived'}).status_code==200
 assert client.post('/api/projects',headers=h,json={'name':'three'}).status_code==201
 assert client.get(f"/api/projects/{p[0]['id']}",headers=h).status_code==200
 assert client.get(f"/api/projects/{p[0]['id']}/export-json",headers=h).status_code==200
 assert client.patch(f"/api/projects/{p[0]['id']}",headers=h,json={'status':'active'}).status_code==409
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'test.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0, result.stdout+result.stderr
