"""R4 union-wide Agent canonical-owner CAS regressions."""
import os,tempfile
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL",f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/agent-union.db")
os.environ.setdefault("APP_ENV","test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN","human-test")
from main import app

H={"Authorization":"Bearer human-test"}
def setup(c):
 p=c.post('/api/projects',json={'name':'union'}).json(); root=c.get(f"/api/nodes/{p['root_node_id']}").json()
 g=c.post('/api/agent-port/grants',headers=H,json={'project_id':p['id'],'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'u','agent_identity':'r4'}).json()
 return p,root,{'Authorization':'Bearer '+g['token']}
def batch(c,h,p,key,ops):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':p['revision'],'idempotency_key':key,'operations':ops})
def state(c,p,n):return c.get(f"/api/projects/{p['id']}").json(),c.get(f"/api/nodes/{n['id']}").json()

def test_missing_owner_cas_is_schema_rejected_without_mutation():
 with TestClient(app) as c:
  p,n,h=setup(c)
  for key,op in [('b',{'op':'create_content_block','node_id':n['id']}),('n',{'op':'create_node','parent_id':n['id'],'title':'x'}),('e',{'op':'create_edge','from_node_id':n['id'],'to_node_id':n['id']}),('r',{'op':'create_branch','source_node_id':n['id'],'name':'x'})]:
   r=batch(c,h,p,'missing-'+key,[op]);assert r.status_code==422,r.text
   assert state(c,p,n)[0]['revision']==p['revision'] and state(c,p,n)[1]['revision']==n['revision']

def test_union_touch_dedupes_and_gui_stale_owner_is_rejected_and_replay_is_exact():
 with TestClient(app) as c:
  p,n,h=setup(c); child='11111111-1111-4111-8111-111111111111'
  ops=[
   {'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision'],'content':{'body':'x'}},
   {'op':'create_node','id':child,'parent_id':n['id'],'expected_parent_revision':n['revision'],'title':'child'},
   {'op':'create_edge','from_node_id':n['id'],'to_node_id':child,'expected_from_revision':n['revision'],'expected_to_revision':1,'relation_type':'supports'},
  ]
  r=batch(c,h,p,'dedupe-001',ops);assert r.status_code==200,r.text
  p2,n2=state(c,p,n);ch=c.get(f'/api/nodes/{child}').json()
  assert p2['revision']==p['revision']+1 and n2['revision']==n['revision']+1 and ch['revision']==1
  stale=c.patch(f"/api/nodes/{n['id']}",json={'expected_project_revision':p2['revision'],'expected_revision':n['revision'],'summary':'stale'})
  assert stale.status_code==409
  replay=batch(c,h,p,'dedupe-001',ops);assert replay.status_code==200 and replay.json()==r.json()
  assert state(c,p,n)[1]['revision']==n2['revision']

def test_stale_reference_rolls_back_entire_batch_and_branch_source_is_cas_read_only():
 with TestClient(app) as c:
  p,n,h=setup(c)
  stale=batch(c,h,p,'rollback-1',[{'op':'create_node','title':'must-not-exist'},{'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision']+1}])
  assert stale.status_code==409
  assert all(x['title']!='must-not-exist' for x in c.get(f"/api/projects/{p['id']}/nodes").json())
  r=batch(c,h,p,'branch-1',[{'op':'create_branch','source_node_id':n['id'],'expected_source_revision':n['revision'],'name':'derived'}])
  assert r.status_code==200,r.text
  p2,n2=state(c,p,n);assert p2['revision']==p['revision']+1 and n2['revision']==n['revision']

def test_malformed_canonical_integrity_error_is_not_flattened_as_idempotency_race(monkeypatch):
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.ext.asyncio import AsyncSession
 from models.models import AgentReceipt
 with TestClient(app) as c:
  p,n,h=setup(c); original=AsyncSession.flush; injected=False
  async def malformed_once(session,*args,**kwargs):
   nonlocal injected
   if not injected and any(isinstance(x,AgentReceipt) for x in session.new):
    injected=True
    raise IntegrityError("redacted statement",{},RuntimeError("private database detail"))
   return await original(session,*args,**kwargs)
  monkeypatch.setattr(AsyncSession,"flush",malformed_once)
  op={'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision'],'content':{'body':'x'}}
  r=batch(c,h,p,'bad-write-1',[op]);assert r.status_code==409,r.text
  detail=r.json()['detail'];assert detail=={'code':'CANONICAL_WRITE_CONFLICT','message':'Atomic canonical write could not be applied'}
  assert 'private database detail' not in r.text and state(c,p,n)[0]['revision']==p['revision']

def test_each_existing_owner_contract_bumps_once_and_stale_is_rejected():
 with TestClient(app) as c:
  p,root,h=setup(c)
  # Create a second existing endpoint through the GUI contract.
  made=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':root['revision'],'title':'endpoint','parent_id':root['id']})
  assert made.status_code==201,made.text
  p,root=state(c,p,root);other=c.get(f"/api/nodes/{made.json()['id']}").json()
  r=batch(c,h,p,'edge-existing-1',[{'op':'create_edge','from_node_id':root['id'],'to_node_id':other['id'],'expected_from_revision':root['revision'],'expected_to_revision':other['revision'],'relation_type':'supports'}])
  assert r.status_code==200,r.text
  p2,root2=state(c,p,root);other2=c.get(f"/api/nodes/{other['id']}").json()
  assert root2['revision']==root['revision']+1 and other2['revision']==other['revision']+1 and p2['revision']==p['revision']+1
  stale=batch(c,h,p2,'edge-stale-1',[{'op':'create_edge','from_node_id':root['id'],'to_node_id':other['id'],'expected_from_revision':root['revision'],'expected_to_revision':other2['revision'],'relation_type':'references'}])
  assert stale.status_code==409 and state(c,p,root)[0]['revision']==p2['revision']
  child=batch(c,h,p2,'parent-existing-1',[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':root2['revision'],'title':'agent child'}])
  assert child.status_code==200,child.text
  assert state(c,p,root)[1]['revision']==root2['revision']+1

def test_true_separate_request_sessions_gui_vs_agent_race_for_every_create_owner():
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 with TestClient(app) as c:
  for kind in ('block','parent','edge','branch'):
   p,root,h=setup(c);other=None
   if kind=='edge':
    made=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':root['revision'],'title':'endpoint','parent_id':root['id']})
    assert made.status_code==201
    p,root=state(c,p,root);other=c.get(f"/api/nodes/{made.json()['id']}").json()
   if kind=='block': op={'op':'create_content_block','node_id':root['id'],'expected_node_revision':root['revision'],'content':{'body':'race'}}
   elif kind=='parent': op={'op':'create_node','parent_id':root['id'],'expected_parent_revision':root['revision'],'title':'race child'}
   elif kind=='edge': op={'op':'create_edge','from_node_id':root['id'],'to_node_id':other['id'],'expected_from_revision':root['revision'],'expected_to_revision':other['revision'],'relation_type':'supports'}
   else: op={'op':'create_branch','source_node_id':root['id'],'expected_source_revision':root['revision'],'name':'race branch'}
   barrier=Barrier(2)
   def agent(): barrier.wait();return batch(c,h,p,'race-'+kind,[op]).status_code
   def gui(): barrier.wait();return c.patch(f"/api/nodes/{root['id']}",json={'expected_project_revision':p['revision'],'expected_revision':root['revision'],'summary':'gui race'}).status_code
   with ThreadPoolExecutor(max_workers=2) as pool:
    a=pool.submit(agent);g=pool.submit(gui);statuses=[a.result(),g.result()]
   assert sorted(statuses)==[200,409],(kind,statuses)
