import os,sys,tempfile,unittest,sqlite3,asyncio,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from fastapi.testclient import TestClient

class R18GlobalAgentAccess(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{cls.tmp.name}/r18.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='r18-human';sys.path.insert(0,str(Path(__file__).parents[1]));import main;cls.client=TestClient(main.app);cls.client.__enter__();cls.human={'Authorization':'Bearer r18-human'}
 @classmethod
 def tearDownClass(cls):cls.client.__exit__(None,None,None);cls.tmp.cleanup()
 def project(self,name):return self.client.post('/api/projects',json={'name':name}).json()
 def workspace(self,mode,persistent=True,expires_at=None):
  body={'workspace_scope':'workspace','mode':mode,'persistent':persistent,'expires_at':expires_at,'label':'R18 test','agent_identity':'test'}
  r=self.client.post('/api/agent-port/grants',headers=self.human,json=body);self.assertEqual(r.status_code,201,r.text);return r.json()
 def auth(self,g):return {'Authorization':'Bearer '+g['token']}
 def revoke(self,g):return self.client.post(f"/api/agent-port/grants/{g['id']}/revoke",headers=self.human)
 def test_atomic_workspace_master_singleton_with_independent_requests(self):
  body={'workspace_scope':'workspace','mode':'direct_collaboration','persistent':True,'expires_at':None,'label':'concurrent master','agent_identity':'test'}
  import agent_port.routes as routes
  barrier=threading.Barrier(2)
  async def race_hook():await asyncio.to_thread(barrier.wait,5)
  routes._workspace_grant_race_hook=race_hook
  def create(_):return self.client.post('/api/agent-port/grants',headers=self.human,json=body)
  try:
   with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(create,range(2)))
  finally:routes._workspace_grant_race_hook=None
  self.assertEqual(sorted(r.status_code for r in responses),[201,409],[r.text for r in responses])
  conflict=next(r for r in responses if r.status_code==409);self.assertEqual(conflict.json()['detail']['code'],'WORKSPACE_GRANT_ACTIVE')
  with sqlite3.connect(Path(self.tmp.name)/'r18.db') as db:
   self.assertEqual(db.execute("SELECT count(*) FROM agent_grants WHERE workspace_scope='workspace' AND status='active' AND revoked_at IS NULL").fetchone()[0],1)
   sql=db.execute("SELECT sql FROM sqlite_schema WHERE type='index' AND name='ux_agent_grants_one_active_workspace'").fetchone()[0]
  from db.schema_contract import WORKSPACE_GRANT_INDEX_SQL,normalize_sql
  self.assertEqual(normalize_sql(sql),normalize_sql(WORKSPACE_GRANT_INDEX_SQL));self.revoke(next(r.json() for r in responses if r.status_code==201))
 def test_atomic_workspace_rotation_exact_identity_and_replay(self):
  old=self.workspace('direct_collaboration');new_id='11111111-1111-4111-8111-111111111111';body={'id':new_id,'workspace_scope':'workspace','mode':'review_first','persistent':True,'expires_at':None,'label':'rotated','agent_identity':'test'}
  rotated=self.client.post(f"/api/agent-port/grants/{old['id']}/rotate",headers=self.human,json=body);self.assertEqual(rotated.status_code,201,rotated.text);self.assertEqual(rotated.json()['id'],new_id)
  replay=self.client.post(f"/api/agent-port/grants/{old['id']}/rotate",headers=self.human,json=body);self.assertEqual(replay.status_code,409);self.assertEqual(replay.json()['detail']['code'],'ROTATION_ALREADY_COMMITTED')
  stale=self.client.post(f"/api/agent-port/grants/{old['id']}/rotate",headers=self.human,json={**body,'id':'22222222-2222-4222-8222-222222222222'});self.assertEqual(stale.status_code,409);self.assertEqual(stale.json()['detail']['code'],'WORKSPACE_GRANT_STALE')
  p=self.project('legacy rotation');legacy=self.client.post('/api/agent-port/grants',headers=self.human,json={'project_id':p['id'],'permission':'read','persistent':True,'expires_at':None,'label':'legacy','agent_identity':'test'}).json();wrong=self.client.post(f"/api/agent-port/grants/{legacy['id']}/rotate",headers=self.human,json={**body,'id':'33333333-3333-4333-8333-333333333333'});self.assertEqual(wrong.status_code,409)
  rows=self.client.get('/api/agent-port/grants',headers=self.human).json();self.assertEqual(sum(x['workspace_scope']=='workspace' and x['status']=='active' and x['revoked_at'] is None for x in rows),1);self.revoke(rotated.json())
 def test_global_explicit_projects_modes_confusion_and_dangerous_absence(self):
  a,b=self.project('R18 A'),self.project('R18 B');read=self.workspace('read_only');h=self.auth(read)
  listed={x['id'] for x in self.client.get('/agent/v1/projects',headers=h).json()};self.assertTrue({a['id'],b['id']}<=listed)
  for route in ('project','graph'):
   self.assertEqual(self.client.get(f'/agent/v1/{route}',headers=h).status_code,422)
   self.assertEqual(self.client.get(f"/agent/v1/{route}?project_id={a['id']}",headers=h).status_code,200)
  self.assertIn(self.client.get(f"/agent/v1/context/{a['root_node_id']}?project_id={b['id']}",headers=h).status_code,(403,404))
  batch={'project_id':a['id'],'expected_project_revision':1,'idempotency_key':'read-denied','operations':[{'op':'update_node','node_id':a['root_node_id'],'expected_revision':1,'fields':{'summary':'no'}}]}
  self.assertEqual(self.client.post('/agent/v1/batch',headers=h,json=batch).status_code,403);self.assertEqual(self.client.post('/agent/v1/proposals',headers=h,json={**batch,'title':'no'}).status_code,403)
  source=(Path(__file__).parents[3]/'scripts/growthmap_mcp.py').read_text(encoding='utf-8')
  for dangerous in ('delete_project','delete_node','execute_command','run_shell'):self.assertNotIn(f'"{dangerous}":',source)
  self.revoke(read);review=self.workspace('review_first');hr=self.auth(review);proposal={**batch,'idempotency_key':'review-pending','title':'pending'}
  made=self.client.post('/agent/v1/proposals',headers=hr,json=proposal);self.assertEqual(made.status_code,201,made.text);self.assertEqual(made.json()['status'],'pending');self.assertEqual(self.client.post('/agent/v1/batch',headers=hr,json=batch).status_code,403)
  approved=self.client.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=self.human,json={});self.assertEqual(approved.status_code,200,approved.text)
  self.revoke(review);direct=self.workspace('direct_collaboration');hd=self.auth(direct);p=self.client.get(f"/agent/v1/project?project_id={b['id']}",headers=hd).json();direct_batch={'project_id':b['id'],'expected_project_revision':p['revision'],'idempotency_key':'direct-safe','operations':[{'op':'create_node','title':'direct','parent_id':b['root_node_id'],'expected_parent_revision':1}]};one=self.client.post('/agent/v1/batch',headers=hd,json=direct_batch);two=self.client.post('/agent/v1/batch',headers=hd,json=direct_batch);self.assertEqual(one.status_code,200,one.text);self.assertEqual(one.json(),two.json())
  listed=self.client.get('/api/agent-port/grants',headers=self.human).json();self.assertEqual(sum(x['workspace_scope']=='workspace' and x['status']=='active' for x in listed),1)
 def test_finite_expired_revoked_and_activity_bounds(self):
  p=self.project('R18 activity');expiry=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat();g=self.workspace('review_first',False,expiry);h=self.auth(g)
  for i in range(110):self.assertEqual(self.client.post('/agent/v1/events',headers=h,json={'project_id':p['id'],'idempotency_key':f'event-{i:03}','event_type':'progress','message':f'event {i}'}).status_code,201)
  activity=self.client.get(f"/api/agent-port/activity?project_id={p['id']}",headers=self.human).json();self.assertLessEqual(len(activity['events']),100)
  self.revoke(g);self.assertEqual(self.client.get(f"/agent/v1/project?project_id={p['id']}",headers=h).status_code,401)
  expired=self.client.post('/api/agent-port/grants',headers=self.human,json={'workspace_scope':'workspace','mode':'read_only','persistent':False,'expires_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),'label':'expired','agent_identity':'test'});self.assertEqual(expired.status_code,422)
