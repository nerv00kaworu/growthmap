"""Subprocess-isolated, file-backed acceptance for shared update_content_block."""
import asyncio, os, tempfile, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/update-block-parity.db")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN", "update-block-human")
from main import app
from db.database import async_session
from models.models import ActionLog, AgentProposal, AgentReceipt, ContentBlock, Edge, Node, Project

ZERO = "00000000-0000-4000-8000-000000000000"
def human_headers(): return {"Authorization":"Bearer "+(os.environ.get("GROWTHMAP_SESSION_TOKEN") or os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"])}
def arun(value): return asyncio.run(value)
def setup(c, name="update-block", child=False):
 p=c.post('/api/projects',json={'name':name}).json(); n=c.get('/api/nodes/'+p['root_node_id']).json()
 if child:
  made=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':n['revision'],'parent_id':n['id'],'title':'child'}); assert made.status_code==201,made.text
  p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json()
 b=c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'block_type':'legacy','content':['old'],'order_index':-1}); assert b.status_code==201,b.text
 return c.get('/api/projects/'+p['id']).json(),c.get('/api/nodes/'+n['id']).json(),b.json()
def grant(c,p,permission='write',node_scope_id=None,identity='update-agent'):
 payload={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'update','agent_identity':identity}
 if node_scope_id: payload['node_scope_id']=node_scope_id
 g=c.post('/api/agent-port/grants',headers=human_headers(),json=payload); assert g.status_code==201,g.text
 return {'Authorization':'Bearer '+g.json()['token']}
def batch(c,h,p,rev,key,ops): return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
async def snapshot(pid, block_ids=()):
 async with async_session() as db:
  p=await db.get(Project,pid)
  ns=(await db.execute(select(Node).where(Node.project_id==pid).order_by(Node.id))).scalars().all()
  if block_ids: bs=(await db.execute(select(ContentBlock).where(ContentBlock.id.in_(block_ids)).order_by(ContentBlock.id))).scalars().all()
  else: bs=(await db.execute(select(ContentBlock).join(Node).where(Node.project_id==pid).order_by(ContentBlock.id))).scalars().all()
  ls=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid).order_by(ActionLog.id))).scalars().all()
  rs=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==pid).order_by(AgentReceipt.id))).scalars().all()
  return p,ns,bs,ls,rs
def stamp(value): return value.isoformat() if value else None
def signature(pid, block_ids=()):
 p,ns,bs,ls,rs=arun(snapshot(pid,block_ids)); return (
  p.revision,stamp(p.updated_at),
  [(n.id,n.revision,stamp(n.updated_at),n.maturity) for n in ns],
  [(b.id,b.node_id,b.revision,stamp(b.updated_at),b.block_type,b.content,b.order_index) for b in bs],
  [(x.id,x.action_type,x.node_id,x.actor_type,x.actor_id,x.payload) for x in ls],
  [(x.id,x.idempotency_key,x.request_digest,x.response) for x in rs])

def test_parity_maturity_history_legacy_json_actor_and_manual_precedence():
 with TestClient(app) as c:
  p,n,b=setup(c,'gui-deep',child=True); secret='SECRET_token_content_value'; previous=(p['updated_at'],n['updated_at'],b['updated_at'])
  values=[(['list',secret],-999), (None,100001), ('scalar',-5), ({'nested':secret},99999)]
  for index,(content,order) in enumerate(values):
   r=c.patch('/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'block_type':f'legacy/free {index}','content':content,'order_index':order})
   assert r.status_code==200,r.text; out=r.json()
   assert (out['authoritative_project_revision'],out['authoritative_node_revision'],out['authoritative_block_revision'])==(p['revision']+1,n['revision']+1,b['revision']+1)
   assert out['content']==content and out['order_index']==order and out['block_type']==f'legacy/free {index}'
   assert out['updated_at']!=b['updated_at']; p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json(); b=out
  assert n['maturity']=='developing' and p['updated_at']!=previous[0] and n['updated_at']!=previous[1]
  history=c.get(f"/api/nodes/{n['id']}/history").json(); updates=[x for x in history if x['action_type']=='update_content_block']
  assert len(updates)==4 and all(x['actor_type']=='human' for x in updates)
  assert secret not in str(updates) and 'token' not in str(updates).lower()
  p2,n2,b2=setup(c,'agent-deep',child=True); h=grant(c,p2['id'],identity='agent-provenance')
  ops=[
   {'op':'update_content_block','block_id':b2['id'],'expected_revision':b2['revision'],'expected_node_revision':n2['revision'],'fields':{'block_type':'paragraph','content':{'body':'safe'},'order_index':8}},
   {'op':'update_node','node_id':n2['id'],'expected_revision':n2['revision'],'fields':{'maturity':'finalized'}},]
  r=batch(c,h,p2['id'],p2['revision'],'agent-maturity-update',ops); assert r.status_code==200,r.text
  body=r.json(); assert body['results'][0]['revision']==b2['revision']+1 and body['results'][0]['node_revision']==n2['revision']+1
  project,nodes,blocks,logs,_=arun(snapshot(p2['id'])); owner=next(x for x in nodes if x.id==n2['id']); block=next(x for x in blocks if x.id==b2['id'])
  log=next(x for x in logs if x.action_type=='update_content_block')
  assert project.revision==p2['revision']+1 and owner.revision==n2['revision']+1 and block.revision==b2['revision']+1 and owner.maturity=='finalized'
  assert log.actor_type=='agent' and log.actor_id=='agent-provenance' and log.payload['provenance']=={'entry':'agent_port','operation_index':0}

def test_validation_scope_orphan_and_create_then_update_are_exact_no_write():
 with TestClient(app) as c:
  p,n,b=setup(c,'validation'); base=signature(p['id'],[b['id']])
  missing=c.patch('/api/blocks/'+ZERO,json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':1,'content':{}})
  assert missing.status_code==404 and missing.json()['detail']=='Block not found' and signature(p['id'],[b['id']])==base
  for field in ('project','node','block'):
   body={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'content':{}}
   body[{'project':'expected_project_revision','node':'expected_node_revision','block':'expected_revision'}[field]]+=99
   r=c.patch('/api/blocks/'+b['id'],json=body); assert r.status_code==409,(field,r.text); assert signature(p['id'],[b['id']])==base
  # Deliberately model a legacy/corrupt orphan with SQLite FK enforcement off.
  async def orphan():
   async with async_session() as db:
    await db.execute(text('PRAGMA foreign_keys=OFF')); await db.execute(text('UPDATE content_blocks SET node_id=:n WHERE id=:b'),{'n':ZERO,'b':b['id']}); await db.commit()
  arun(orphan()); orphaned=signature(p['id'],[b['id']])
  r=c.patch('/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'content':{}})
  assert r.status_code==404 and r.json()['detail']=='Node not found' and signature(p['id'],[b['id']])==orphaned

  p,n,b=setup(c,'agent-validation'); child=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':n['revision'],'parent_id':n['id'],'title':'other'}).json()
  p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json(); h=grant(c,p['id'],node_scope_id=child['id']); base=signature(p['id'],[b['id']])
  valid={'op':'update_content_block','block_id':b['id'],'expected_revision':b['revision'],'expected_node_revision':n['revision'],'fields':{'content':{'x':'y'}}}
  denied=batch(c,h,p['id'],p['revision'],'scope-denied',[valid]); assert denied.status_code==403 and signature(p['id'],[b['id']])==base
  h=grant(c,p['id']); invalids=[
   {**valid,'extra':1}, {**valid,'fields':{}}, {**valid,'fields':{'content':None}}, {**valid,'fields':{'block_type':'legacy'}},
   {**valid,'fields':{'content':{str(i):'x' for i in range(101)}}}, {**valid,'fields':{'content':{'k'*101:'x'}}},
   {**valid,'fields':{'content':{'x':'v'*16385}}}, {**valid,'fields':{'order_index':-1}}, {**valid,'fields':{'order_index':100001}}]
  for i,op in enumerate(invalids):
   r=batch(c,h,p['id'],p['revision'],f'invalid-update-{i}',[op]); assert r.status_code==422,(i,r.text); assert signature(p['id'],[b['id']])==base
  new_id=str(uuid.uuid4()); ops=[{'op':'create_content_block','id':new_id,'node_id':n['id'],'expected_node_revision':n['revision'],'content':{}},{'op':'update_content_block','block_id':new_id,'expected_revision':1,'expected_node_revision':n['revision'],'fields':{'content':{'x':'y'}}}]
  r=batch(c,h,p['id'],p['revision'],'create-then-update',ops); assert r.status_code==422 and r.json()['detail']=={'code':'NEW_BLOCK_UPDATE_UNSUPPORTED','message':'update_content_block supports pre-existing blocks only'}
  assert signature(p['id'],[b['id'],new_id])==base

def test_union_multi_update_multi_block_mixed_results_replay_and_maturity():
 with TestClient(app) as c:
  p,n,b1=setup(c,'union',child=True)
  made=c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'content':{'body':'second'}}); assert made.status_code==201,made.text
  b2=made.json(); p=c.get('/api/projects/'+p['id']).json(); n=c.get('/api/nodes/'+n['id']).json(); h=grant(c,p['id']); new_node=str(uuid.uuid4())
  ops=[
   {'op':'update_content_block','block_id':b1['id'],'expected_revision':b1['revision'],'expected_node_revision':n['revision'],'fields':{'content':{'body':'one'}}},
   {'op':'create_node','id':new_node,'parent_id':n['id'],'expected_parent_revision':n['revision'],'title':'mixed'},
   {'op':'update_content_block','block_id':b2['id'],'expected_revision':b2['revision'],'expected_node_revision':n['revision'],'fields':{'order_index':7}},
   {'op':'update_content_block','block_id':b1['id'],'expected_revision':b1['revision'],'expected_node_revision':n['revision'],'fields':{'block_type':'code'}},
   {'op':'create_edge','from_node_id':new_node,'to_node_id':n['id'],'expected_from_revision':1,'expected_to_revision':n['revision'],'relation_type':'supports'},
   {'op':'create_content_block','node_id':new_node,'expected_node_revision':1,'content':{'body':'new'}},
   {'op':'update_node','node_id':n['id'],'expected_revision':n['revision'],'fields':{'maturity':'finalized'}},]
  before=signature(p['id']); r=batch(c,h,p['id'],p['revision'],'mixed-update-replay',ops); assert r.status_code==200,r.text; body=r.json()
  assert [x['op'] for x in body['results']]==[x['op'] for x in ops]
  project,nodes,blocks,logs,receipts=arun(snapshot(p['id'])); byn={x.id:x for x in nodes}; byb={x.id:x for x in blocks}
  assert project.revision==p['revision']+1 and byn[n['id']].revision==n['revision']+1 and byn[n['id']].maturity=='finalized'
  assert byb[b1['id']].revision==b1['revision']+1 and byb[b2['id']].revision==b2['revision']+1 and byn[new_node].revision==2
  updates=[x for x in logs if x.action_type=='update_content_block']; assert len(updates)==3 and len(receipts)==1
  assert [body['results'][i]['revision'] for i in (0,2,3)]==[b1['revision']+1,b2['revision']+1,b1['revision']+1]
  assert all(body['results'][i]['node_revision']==n['revision']+1 for i in (0,2,3))
  after=signature(p['id']); replay=batch(c,h,p['id'],p['revision'],'mixed-update-replay',ops); assert replay.status_code==200 and replay.json()==body and signature(p['id'])==after and before!=after

def test_post_cas_exception_rolls_back_gui_agent_and_proposal(monkeypatch):
 import api.routes as gui_routes
 import agent_port.service as agent_service
 original=agent_service.apply_update_content_block
 async def explode(db,*args,**kwargs):
  block=await original(db,*args,**kwargs); await db.flush()
  assert block.content=={'boom':'mutated'}
  count=(await db.execute(select(func.count()).select_from(ActionLog).where(ActionLog.action_type=='update_content_block',ActionLog.node_id==block.node_id))).scalar_one(); assert count>=1
  raise RuntimeError('post-CAS injected failure')
 monkeypatch.setattr(gui_routes,'apply_update_content_block',explode); monkeypatch.setattr(agent_service,'apply_update_content_block',explode)
 with TestClient(app,raise_server_exceptions=False) as c:
  p,n,b=setup(c,'rollback-gui',child=True); before=signature(p['id'],[b['id']]); r=c.patch('/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'content':{'boom':'mutated'}}); assert r.status_code==500 and signature(p['id'],[b['id']])==before
  p,n,b=setup(c,'rollback-agent',child=True); h=grant(c,p['id']); before=signature(p['id'],[b['id']]); op={'op':'update_content_block','block_id':b['id'],'expected_revision':b['revision'],'expected_node_revision':n['revision'],'fields':{'content':{'boom':'mutated'}}}
  assert batch(c,h,p['id'],p['revision'],'rollback-direct',[op]).status_code==500 and signature(p['id'],[b['id']])==before
  p,n,b=setup(c,'rollback-proposal',child=True); h=grant(c,p['id'],'propose'); op={'op':'update_content_block','block_id':b['id'],'expected_revision':b['revision'],'expected_node_revision':n['revision'],'fields':{'content':{'boom':'mutated'}}}
  made=c.post('/agent/v1/proposals',headers=h,json={'expected_project_revision':p['revision'],'idempotency_key':'proposal-update-one','title':'update','operations':[op]}); assert made.status_code==201,made.text
  before=signature(p['id'],[b['id']]); review=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=human_headers(),json={'review_note':'must rollback'}); assert review.status_code==500 and signature(p['id'],[b['id']])==before
  async def proposal():
   async with async_session() as db: return await db.get(AgentProposal,made.json()['proposal_id'])
  row=arun(proposal()); assert row.status=='pending' and row.reviewed_at is None and row.review_note==''

def test_file_backed_gui_agent_update_race_three_rounds_separate_clients():
 for run in range(3):
  with TestClient(app) as seed:
   p,n,b=setup(seed,f'race-update-{run}',child=True); h=grant(seed,p['id'])
  barrier=Barrier(2)
  def gui():
   with TestClient(app) as c: barrier.wait(); return ('gui',c.patch('/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'content':{'winner':'gui'}}).status_code)
  def agent():
   op={'op':'update_content_block','block_id':b['id'],'expected_revision':b['revision'],'expected_node_revision':n['revision'],'fields':{'content':{'winner':'agent'}}}
   with TestClient(app) as c: barrier.wait(); return ('agent',batch(c,h,p['id'],p['revision'],f'race-update-{run}',[op]).status_code)
  with ThreadPoolExecutor(max_workers=2) as pool: outcomes=[pool.submit(gui),pool.submit(agent)]; outcomes=[x.result() for x in outcomes]
  assert sorted(code for _,code in outcomes)==[200,409],outcomes; winner=next(name for name,code in outcomes if code==200)
  project,nodes,blocks,logs,receipts=arun(snapshot(p['id'])); owner=next(x for x in nodes if x.id==n['id']); block=next(x for x in blocks if x.id==b['id'])
  assert project.revision==p['revision']+1 and owner.revision==n['revision']+1 and block.revision==b['revision']+1 and block.content=={'winner':winner}
  assert len([x for x in logs if x.action_type=='update_content_block'])==1 and len(receipts)==int(winner=='agent')
