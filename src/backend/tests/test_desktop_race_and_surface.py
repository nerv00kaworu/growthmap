import os,subprocess,sys

def run(script,env):
 r=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr

def test_authoring_desktop_routes_are_404(tmp_path):
 env={**os.environ,'APP_ENV':'test','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'a.db'}"};env.pop('GROWTHMAP_DESKTOP_MODE',None);env.pop('GROWTHMAP_SESSION_TOKEN',None)
 run("from fastapi.testclient import TestClient;from main import app;c=TestClient(app);assert c.put('/api/desktop/secrets/x',json={'api_key':'x'}).status_code==404;assert c.post('/api/desktop/license/import',json={'document':{}}).status_code==404",env)

def test_concurrent_create_and_restore_never_exceed_two(tmp_path):
 script=r'''
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer test-session-token'}
with TestClient(app) as c:
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 def create(n):return c.post('/api/projects',headers=h,json={'name':n}).status_code
 with ThreadPoolExecutor(max_workers=8) as x: codes=list(x.map(create,[str(i) for i in range(8)]))
 rows=c.get('/api/projects',headers=h).json();assert sum(p['status']=='active' for p in rows)<=2,codes
 for p in rows:c.patch(f"/api/projects/{p['id']}",headers=h,json={'status':'archived','expected_project_revision':p['revision']})
 # Seed archived projects without consuming seats, then restore concurrently.
 archived=[]
 for i in range(6):
  p=c.post('/api/projects',headers=h,json={'name':f'r{i}'}).json();c.patch(f"/api/projects/{p['id']}",headers=h,json={'status':'archived','expected_project_revision':p['revision']});p['revision']+=1;archived.append(p)
 def restore(p):return c.patch(f"/api/projects/{p['id']}",headers=h,json={'status':'active','expected_project_revision':p['revision']}).status_code
 with ThreadPoolExecutor(max_workers=6) as x:codes=list(x.map(restore,archived))
 rows=c.get('/api/projects',headers=h).json();assert sum(p['status']=='active' for p in rows)<=2,codes
'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'r.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')};run(script,env)
