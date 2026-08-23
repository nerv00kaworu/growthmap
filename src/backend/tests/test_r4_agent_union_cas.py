"""R4 union-wide Agent canonical-owner CAS regressions."""
import os,tempfile
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"]=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/agent-union.db"
os.environ.setdefault("APP_ENV","test")
os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"]="human-test"
from main import app

_state=None
def setup_module():
 global _state
 from tests.r4_harness import setup_r4;_state=setup_r4('agent-union')
def teardown_module():
 from tests.r4_harness import teardown_r4;teardown_r4(_state)

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

def test_agent_branch_canonical_copy_provided_id_replay_and_same_batch_ref():
 from db.database import async_session
 from models.models import Branch,ContentBlock,Edge,Node
 from sqlalchemy import select
 import asyncio
 with TestClient(app) as c:
  p,root,h=setup(c)
  child=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':root['revision'],'title':'child','parent_id':root['id']}).json()
  p,root=state(c,p,root)
  grand=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':child['revision'],'title':'grand','parent_id':child['id']}).json()
  p,root=state(c,p,root)
  made=c.post(f"/api/nodes/{root['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':root['revision'],'block_type':'code','content':{'nested':['x']},'order_index':7});assert made.status_code==201,made.text
  p,root=state(c,p,root);bid='22222222-2222-4222-8222-222222222222';nid='33333333-3333-4333-8333-333333333333'
  ops=[{'op':'create_branch','id':bid,'source_node_id':root['id'],'expected_source_revision':root['revision'],'name':'copy'}, {'op':'create_node','id':nid,'title':'same batch','branch_id':bid}]
  r=batch(c,h,p,'tree-copy',ops);assert r.status_code==200,r.text
  assert batch(c,h,p,'tree-copy',ops).json()==r.json()
  async def rows():
   async with async_session() as db:
    branch=await db.get(Branch,bid);nodes=(await db.execute(select(Node).where(Node.branch_id==bid))).scalars().all();ids={n.id for n in nodes};blocks=(await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(ids)))).scalars().all();edges=(await db.execute(select(Edge).where(Edge.from_node_id.in_(ids),Edge.to_node_id.in_(ids)))).scalars().all();return branch,nodes,blocks,edges
  branch,nodes,blocks,edges=asyncio.run(rows())
  assert branch.status=='active' and branch.revision==1
  assert sorted(n.title for n in nodes)==['child','grand','same batch','union'] and all(n.revision==1 and n.branch_id==bid for n in nodes)
  assert len(blocks)==1 and blocks[0].content=={'nested':['x']} and blocks[0].order_index==0 and blocks[0].revision==1
  assert len(edges)==2 and all(e.relation_type=='child_of' and e.revision==1 for e in edges)
  assert c.get(f"/api/nodes/{root['id']}").json()['revision']==root['revision']

def test_forward_branch_reference_is_dependency_ordered_atomically_and_cycles_roll_back():
 from db.database import async_session
 from models.models import ActionLog,AgentReceipt,Branch,Node,Project
 from sqlalchemy import select
 import asyncio
 with TestClient(app) as c:
  p,root,h=setup(c);bid='88444444-4444-4444-8444-444444444448';nid='88555555-5555-4555-8555-555555555558'
  ops=[{'op':'create_node','id':nid,'title':'forward node','branch_id':bid}, {'op':'create_branch','id':bid,'source_node_id':root['id'],'expected_source_revision':root['revision'],'name':'later branch'}]
  r=batch(c,h,p,'forward-branch',ops);assert r.status_code==200,r.text
  body=r.json();assert body['project_revision']==p['revision']+1 and [x['id'] for x in body['results']]==[nid,bid]
  assert batch(c,h,p,'forward-branch',ops).json()==body
  async def committed():
   async with async_session() as db:
    project=await db.get(Project,p['id']);branch=await db.get(Branch,bid);node=await db.get(Node,nid)
    receipts=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p['id'],AgentReceipt.idempotency_key=='forward-branch'))).scalars().all()
    logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==p['id'],ActionLog.action_type=='agent_batch_applied'))).scalars().all()
    return project,branch,node,receipts,logs
  project,branch,node,receipts,logs=asyncio.run(committed())
  assert project.revision==p['revision']+1 and branch.revision==node.revision==1 and node.branch_id==bid
  assert len(receipts)==1 and receipts[0].response==body and len(logs)==1 and logs[0].payload['receipt_id']==body['receipt_id']

  # This graph is schema- and scope-valid: the node is contained by the existing
  # root, while its branch is produced by a branch copy sourced from that node.
  # Neither create can execute first, so the dependency sorter must reject it.
  p2,root2,h2=setup(c);cyclic_branch='88666666-6666-4666-8666-666666666668';cyclic_node='88777777-7777-4777-8777-777777777778'
  cycle=[
   {'op':'create_node','id':cyclic_node,'title':'cycle node','parent_id':root2['id'],'expected_parent_revision':root2['revision'],'branch_id':cyclic_branch},
   {'op':'create_branch','id':cyclic_branch,'source_node_id':cyclic_node,'expected_source_revision':1,'name':'cycle branch'},
  ]
  bad=batch(c,h2,p2,'cycle-001',cycle);assert bad.status_code==422,bad.text
  assert bad.json()['detail']=={'code':'CYCLIC_BATCH_DEPENDENCY','message':'Atomic batch contains cyclic create dependencies'},bad.text
  assert c.get(f"/api/projects/{p2['id']}").json()['revision']==p2['revision']
  assert c.get(f'/api/nodes/{cyclic_node}').status_code==404
  async def absent():
   async with async_session() as db:
    return await db.get(Branch,cyclic_branch),(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p2['id'],AgentReceipt.idempotency_key=='cycle-001'))).scalars().all()
  branch2,receipts2=asyncio.run(absent());assert branch2 is None and receipts2==[]

def test_forward_created_node_dependents_preserve_results_and_never_500():
 """Later create producers cover edge/block; updates of new nodes stay rejected."""
 with TestClient(app) as c:
  p,root,h=setup(c);a='88888888-8888-4888-8888-888888888881';b='88888888-8888-4888-8888-888888888882'
  # Scope containment must be established before an op can reference a new node.
  # Once established, mixed dependent creates retain caller-visible result order.
  ops=[
   {'op':'create_node','id':a,'title':'a','parent_id':root['id'],'expected_parent_revision':root['revision']},
   {'op':'create_node','id':b,'title':'b','parent_id':a,'expected_parent_revision':1},
   {'op':'create_edge','from_node_id':a,'to_node_id':b,'expected_from_revision':1,'expected_to_revision':1,'relation_type':'supports'},
   {'op':'create_content_block','node_id':b,'expected_node_revision':1,'content':{'body':'ok'}},
  ]
  r=batch(c,h,p,'dependent-creates',ops);assert r.status_code==200,r.text
  assert [item['op'] for item in r.json()['results']]==[op['op'] for op in ops]
  p2=c.get(f"/api/projects/{p['id']}").json();assert p2['revision']==p['revision']+1
  update=batch(c,h,p2,'new-update',[{'op':'create_node','id':'88888888-8888-4888-8888-888888888883','title':'new'}, {'op':'update_node','node_id':'88888888-8888-4888-8888-888888888883','expected_revision':1,'fields':{'summary':'no'}}])
  assert update.status_code==422 and update.json()['detail']=='Cannot update a not-yet-created node'
  assert c.get(f"/api/projects/{p['id']}").json()['revision']==p2['revision']
