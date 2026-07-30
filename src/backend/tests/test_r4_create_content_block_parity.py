"""Subprocess-isolated, file-backed acceptance for shared create_content_block."""
import asyncio, os, tempfile, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from fastapi.testclient import TestClient
from sqlalchemy import func, select

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/blocks-parity.db")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN", "block-human")
from main import app
from db.database import async_session
from models.models import ActionLog, AgentProposal, AgentReceipt, ContentBlock, Edge, Node, Project

def human_headers(): return {"Authorization":"Bearer "+(os.environ.get("GROWTHMAP_SESSION_TOKEN") or os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"])}
def arun(value): return asyncio.run(value)
def setup(c,name="blocks"):
 p=c.post('/api/projects',json={'name':name}).json(); n=c.get('/api/nodes/'+p['root_node_id']).json(); return p,n
def grant(c,p,permission='write',node_scope_id=None):
 payload={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'block','agent_identity':'block-agent'}
 if node_scope_id: payload['node_scope_id']=node_scope_id
 g=c.post('/api/agent-port/grants',headers=human_headers(),json=payload).json(); return {'Authorization':'Bearer '+g['token']}
def batch(c,h,p,key,ops,rev): return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
async def snapshot(pid):
 async with async_session() as db:
  p=await db.get(Project,pid)
  nodes=(await db.execute(select(Node).where(Node.project_id==pid).order_by(Node.id))).scalars().all()
  blocks=(await db.execute(select(ContentBlock).join(Node).where(Node.project_id==pid))).scalars().all()
  logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid))).scalars().all()
  receipts=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==pid))).scalars().all()
  return p, nodes, blocks, logs, receipts
def sig(pid):
 p,ns,bs,ls,rs=arun(snapshot(pid)); return (p.revision,[(n.id,n.revision,n.maturity) for n in ns],len(bs),len(ls),len(rs))

def test_parity_maturity_history_and_gui_legacy_json_contract():
 with TestClient(app) as c:
  # A child makes the first block advance seed directly to developing.
  p,n=setup(c,'gui'); child=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':n['revision'],'parent_id':n['id'],'title':'child'}); assert child.status_code==201
  p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json()
  secret='SECRET_TOKEN_DO_NOT_LOG'
  r=c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'block_type':'legacy/free form','content':[secret,{'token':secret}],'order_index':-77})
  assert r.status_code==201,r.text
  history=c.get(f"/api/nodes/{n['id']}/history").json(); create=next(x for x in history if x['action_type']=='create_content_block')
  assert secret not in str(create) and create['actor_type']=='human'
  assert create['payload']['content_shape']=='array' and create['payload']['content_item_count']==2
  p1,ns,bs,logs,_=arun(snapshot(p['id'])); owner=next(x for x in ns if x.id==n['id']); log=next(x for x in logs if x.action_type=='create_content_block')
  assert owner.maturity=='developing' and (p1.revision,owner.revision,bs[0].revision)==(p['revision']+1,n['revision']+1,1)
  assert bs[0].content==[secret,{'token':secret}] and bs[0].block_type=='legacy/free form' and bs[0].order_index==-77
  assert log.actor_id in (None,'') and log.payload['provenance']=={'entry':'gui_rest'}
  # Agent remains strict and gets equal canonical block/history semantics.
  p2,n2=setup(c,'agent'); h=grant(c,p2['id']); out=batch(c,h,p2['id'],'parity-001',[{'op':'create_content_block','node_id':n2['id'],'expected_node_revision':1,'block_type':'paragraph','content':{'body':'safe'},'order_index':2}],p2['revision'])
  assert out.status_code==200,out.text
  _,_,blocks,logs,_=arun(snapshot(p2['id'])); alog=next(x for x in logs if x.action_type=='create_content_block')
  assert len(blocks)==1 and alog.actor_type=='agent' and alog.actor_id=='block-agent' and alog.payload['content_key_count']==1

def test_validation_adapters_are_no_write_and_exact_scope_is_403():
 with TestClient(app) as c:
  p,n=setup(c,'validation'); baseline=sig(p['id'])
  missing=c.post('/api/nodes/00000000-0000-4000-8000-000000000000/blocks',json={'expected_project_revision':1,'expected_node_revision':1})
  assert missing.status_code==404 and missing.json()['detail']=='Node not found' and sig(p['id'])==baseline
  for payload in ({'expected_project_revision':999,'expected_node_revision':1},{'expected_project_revision':1,'expected_node_revision':999}):
   assert c.post(f"/api/nodes/{n['id']}/blocks",json=payload).status_code==409 and sig(p['id'])==baseline
  child=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':1,'expected_parent_revision':1,'parent_id':n['id'],'title':'other'}).json(); p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json(); base=sig(p['id']); scoped=grant(c,p['id'],node_scope_id=n['id'])
  valid={'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision'],'content':{}}
  invalids=[
   ({**valid,'node_id':child['id'],'expected_node_revision':1},403),({**valid,'extra':1},422),({**valid,'block_type':'legacy'},422),
   ({**valid,'content':{str(i):'x' for i in range(101)}},422),({**valid,'content':{'k'*101:'x'}},422),
   ({**valid,'content':{'x':'v'*16385}},422),({**valid,'order_index':-1},422),({**valid,'order_index':100001},422)]
  for i,(op,status) in enumerate(invalids):
   r=batch(c,scoped,p['id'],f'invalid-{i:02d}',[op],p['revision']); assert r.status_code==status,(i,r.text); assert sig(p['id'])==base

def test_union_forward_replay_and_manual_maturity_precedence():
 with TestClient(app) as c:
  p,root=setup(c,'union'); h=grant(c,p['id']); a=str(uuid.uuid4()); b=str(uuid.uuid4())
  ops=[
   {'op':'create_content_block','node_id':root['id'],'expected_node_revision':1,'content':{'body':'one'}},
   {'op':'create_node','id':a,'parent_id':root['id'],'expected_parent_revision':1,'title':'new'},
   {'op':'create_content_block','node_id':root['id'],'expected_node_revision':1,'content':{'body':'two'}},
   {'op':'create_content_block','node_id':a,'expected_node_revision':1,'content':{'body':'new-owner'}},
   {'op':'update_node','node_id':root['id'],'expected_revision':1,'fields':{'maturity':'finalized'}},
   {'op':'create_edge','from_node_id':root['id'],'to_node_id':a,'expected_from_revision':1,'expected_to_revision':1,'relation_type':'supports'},
   {'op':'create_node','id':b,'parent_id':a,'expected_parent_revision':1,'title':'forward child'},]
  r=batch(c,h,p['id'],'union-replay-001',ops,p['revision']); assert r.status_code==200,r.text; body=r.json()
  assert [x['op'] for x in body['results']]==[x['op'] for x in ops]
  p1,ns,blocks,logs,receipts=arun(snapshot(p['id'])); by={n.id:n for n in ns}
  assert p1.revision==p['revision']+1 and by[root['id']].revision==2 and by[root['id']].maturity=='finalized'
  assert by[a].revision==2 and by[b].revision==1 and len(blocks)==3 and all(x.revision==1 for x in blocks)
  assert len([x for x in logs if x.action_type=='create_content_block'])==3 and len(receipts)==1
  replay=batch(c,h,p['id'],'union-replay-001',ops,p['revision']); assert replay.status_code==200 and replay.json()==body
  assert sig(p['id'])==(p1.revision,[(n.id,n.revision,n.maturity) for n in ns],3,len(logs),1)

def test_post_cas_exception_rolls_back_gui_agent_and_proposal(monkeypatch):
 import api.routes as gui_routes
 import agent_port.service as agent_service
 original=agent_service.apply_create_content_block
 async def explode(db,*args,**kwargs):
  block=await original(db,*args,**kwargs); await db.flush()
  assert await db.get(ContentBlock,block.id)
  count=(await db.execute(select(func.count()).select_from(ActionLog).where(ActionLog.action_type=='create_content_block',ActionLog.node_id==block.node_id))).scalar_one(); assert count>=1
  raise RuntimeError('post-CAS injected failure')
 monkeypatch.setattr(gui_routes,'apply_create_content_block',explode); monkeypatch.setattr(agent_service,'apply_create_content_block',explode)
 with TestClient(app,raise_server_exceptions=False) as c:
  # GUI direct.
  p,n=setup(c,'rollback-gui'); before=sig(p['id']); assert c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':1,'expected_node_revision':1,'content':{}}).status_code==500; assert sig(p['id'])==before
  # Agent direct.
  p,n=setup(c,'rollback-agent'); h=grant(c,p['id']); before=sig(p['id']); op={'op':'create_content_block','node_id':n['id'],'expected_node_revision':1,'content':{}}
  assert batch(c,h,p['id'],'rollback-direct',[op],1).status_code==500 and sig(p['id'])==before
  # Proposal approval remains pending with untouched review fields.
  p,n=setup(c,'rollback-proposal'); h=grant(c,p['id'],'propose'); proposal_op={'op':'create_content_block','node_id':n['id'],'expected_node_revision':1,'content':{}}; made=c.post('/agent/v1/proposals',headers=h,json={'expected_project_revision':1,'idempotency_key':'proposal-create-1','title':'block','operations':[proposal_op]}).json(); before=sig(p['id'])
  review=c.post(f"/api/agent-port/proposals/{made['proposal_id']}/approve",headers=human_headers(),json={'review_note':'must rollback'}); assert review.status_code==500 and sig(p['id'])==before
  async def proposal():
   async with async_session() as db:return await db.get(AgentProposal,made['proposal_id'])
  row=arun(proposal()); assert row.status=='pending' and row.reviewed_at is None and row.review_note==''

def test_file_backed_gui_agent_race_three_times_separate_clients():
 for run in range(3):
  with TestClient(app) as seed:
   p,n=setup(seed,f'race-{run}'); h=grant(seed,p['id'])
  barrier=Barrier(2)
  def gui():
   with TestClient(app) as c: barrier.wait(); return c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':1,'expected_node_revision':1,'content':['gui']}).status_code
  def agent():
   with TestClient(app) as c: barrier.wait(); return batch(c,h,p['id'],f'race-agent-{run}',[{'op':'create_content_block','node_id':n['id'],'expected_node_revision':1,'content':{'body':'agent'}}],1).status_code
  with ThreadPoolExecutor(max_workers=2) as pool: statuses=[pool.submit(gui),pool.submit(agent)]; statuses=[x.result() for x in statuses]
  assert len([x for x in statuses if 200 <= x < 300])==1 and statuses.count(409)==1,statuses
  project,nodes,blocks,logs,receipts=arun(snapshot(p['id'])); owner=next(x for x in nodes if x.id==n['id'])
  assert project.revision==2 and owner.revision==2 and len(blocks)==1 and len([x for x in logs if x.action_type=='create_content_block'])==1
  assert len(receipts)==int(blocks[0].created_by=='block-agent')
