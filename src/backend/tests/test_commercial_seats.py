import os,subprocess,sys
from pathlib import Path

def test_import_seat_and_concurrent_create_import_restore(tmp_path):
 code=r'''import concurrent.futures
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer t'}
active={'project':{'name':'imported','status':'active'},'nodes':[],'edges':[],'content_blocks':[]}
archived={'project':{'name':'archive','status':'archived'},'nodes':[],'edges':[],'content_blocks':[]}
with TestClient(app) as c:
 assert c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'}).status_code==200
 assert c.post('/api/projects',headers=h,json={'name':'one'}).status_code==201
 assert c.post('/api/projects/import-json',headers=h,json=active).status_code==402
 assert c.post('/api/projects/import-json',headers=h,json=active).status_code==402
 assert c.post('/api/projects/import-json',headers=h,json=archived).status_code==201
 rows=c.get('/api/projects',headers=h).json();active_row=next(p for p in rows if p['status']=='active');archived_id=next(p['id'] for p in rows if p['status']=='archived')
 # Reaching quota never blocks reads or exports, and deleting the sole active project
 # frees the concurrent-active seat for restoring an archived project.
 assert c.get('/api/projects/'+active_row['id']+'/export',headers=h).status_code==200
 assert c.patch('/api/projects/'+archived_id,headers=h,json={'status':'active','expected_project_revision':next(p['revision'] for p in c.get('/api/projects',headers=h).json() if p['id']==archived_id)}).status_code==409
 assert c.request('DELETE','/api/projects/'+active_row['id'],headers=h,json={'expected_project_revision':active_row['revision']}).status_code==204
 restored=c.patch('/api/projects/'+archived_id,headers=h,json={'status':'active','expected_project_revision':next(p['revision'] for p in c.get('/api/projects',headers=h).json() if p['id']==archived_id)})
 assert restored.status_code==200
 assert c.post('/api/projects/import-json',headers=h,json=active).status_code==402
# Fresh DB concurrency: mixed allocators can produce at most one success.
'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'t','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'00ea2c7a12956fa4fff2f382fa32b3bafd333082d7f6765f1ad6edb5741b9218','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'seat.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
 r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
 code2=r'''import concurrent.futures
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer t'}; active={'project':{'name':'i','status':'active'},'nodes':[],'edges':[],'content_blocks':[]}
with TestClient(app) as c:
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 def call(i):
  return (c.post('/api/projects',headers=h,json={'name':str(i)}) if i%2==0 else c.post('/api/projects/import-json',headers=h,json=active)).status_code
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: codes=list(pool.map(call,range(6)))
 assert codes.count(201)==1,codes
 assert len([p for p in c.get('/api/projects',headers=h).json() if p['status']=='active'])==1
'''
 env['DATABASE_URL']=f"sqlite+aiosqlite:///{tmp_path/'concurrent.db'}";env['GROWTHMAP_TRIAL_STATE_FILE']=str(tmp_path/'trial2.json')
 r=subprocess.run([sys.executable,'-c',code2],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
