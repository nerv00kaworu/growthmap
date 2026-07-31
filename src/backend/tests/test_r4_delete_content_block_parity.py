"""Focused file-backed acceptance for shared delete_content_block."""
import asyncio, os, tempfile, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from fastapi.testclient import TestClient
from sqlalchemy import select, text
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/delete-block-parity.db")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN", "delete-block-human")
from main import app
from db.database import async_session
from models.models import ActionLog, AgentProposal, AgentReceipt, ContentBlock, Node, Project
ZERO="00000000-0000-4000-8000-000000000000"
def hh(): return {"Authorization":"Bearer "+(os.environ.get("GROWTHMAP_SESSION_TOKEN") or os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"])}
def arun(x): return asyncio.run(x)
def setup(c,name="delete"):
 p=c.post('/api/projects',json={'name':name}).json(); n=c.get('/api/nodes/'+p['root_node_id']).json()
 b=c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'block_type':'paragraph','content':{'secret':'NEVER_LOG_ME'},'order_index':3}); assert b.status_code==201,b.text
 return c.get('/api/projects/'+p['id']).json(),c.get('/api/nodes/'+n['id']).json(),b.json()
def grant(c,p,permission='write',scope=None,identity='delete-agent'):
 d={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'delete','agent_identity':identity}
 if scope:d['node_scope_id']=scope
 r=c.post('/api/agent-port/grants',headers=hh(),json=d); assert r.status_code==201,r.text
 return {'Authorization':'Bearer '+r.json()['token']}
def op(n,b): return {'op':'delete_content_block','block_id':b['id'],'expected_revision':b['revision'],'expected_node_revision':n['revision']}
def batch(c,h,p,key,ops): return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':p['revision'],'idempotency_key':key,'operations':ops})
async def snap(pid,bid):
 async with async_session() as db:
  p=await db.get(Project,pid); ns=(await db.execute(select(Node).where(Node.project_id==pid))).scalars().all(); b=await db.get(ContentBlock,bid)
  ls=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid).order_by(ActionLog.id))).scalars().all(); rs=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==pid))).scalars().all()
  return p,ns,b,ls,rs
def sig(pid,bid):
 p,ns,b,ls,rs=arun(snap(pid,bid)); return (p.revision,[(n.id,n.revision,n.maturity,str(n.updated_at)) for n in ns],None if not b else (b.revision,b.content),[(x.action_type,x.actor_type,x.actor_id,x.payload) for x in ls],[(r.id,r.response) for r in rs])

def test_gui_and_agent_happy_history_sanitized_replay_and_mismatch():
 with TestClient(app) as c:
  p,n,b=setup(c,'gui'); r=c.request('DELETE','/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision']}); assert r.status_code==204,r.text
  P,N,B,L,R=arun(snap(p['id'],b['id'])); owner=next(x for x in N if x.id==n['id']); log=next(x for x in L if x.action_type=='delete_content_block')
  assert B is None and P.revision==p['revision']+1 and owner.revision==n['revision']+1 and log.actor_type=='human' and log.payload=={'block_id':b['id'],'node_id':n['id'],'provenance':{'entry':'gui_rest'}} and 'NEVER_LOG_ME' not in str(log.payload)
  p,n,b=setup(c,'agent'); h=grant(c,p['id'],identity='agent-seven'); body=batch(c,h,p,'same-delete',[op(n,b)]); assert body.status_code==200,body.text; out=body.json(); after=sig(p['id'],b['id'])
  assert out['results']==[{'op':'delete_content_block','id':b['id'],'node_id':n['id'],'node_revision':n['revision']+1}]
  assert batch(c,h,p,'same-delete',[op(n,b)]).json()==out and sig(p['id'],b['id'])==after
  changed={**op(n,b),'expected_revision':b['revision']+1}; assert batch(c,h,p,'same-delete',[changed]).status_code==409
  _,_,_,logs,receipts=arun(snap(p['id'],b['id'])); dl=[x for x in logs if x.action_type=='delete_content_block']; assert len(dl)==1 and dl[0].actor_id=='agent-seven' and len(receipts)==1 and 'NEVER_LOG_ME' not in str(dl[0].payload)

def test_strict_scope_conflicts_duplicate_dependency_and_missing_no_write():
 with TestClient(app) as c:
  p,n,b=setup(c,'checks'); h=grant(c,p['id']); base=sig(p['id'],b['id'])
  for bad in [{**op(n,b),'node_id':n['id']},{**op(n,b),'content':{}},{**op(n,b),'expected_revision':'1'},{k:v for k,v in op(n,b).items() if k!='expected_node_revision'}]:
   assert batch(c,h,p,str(uuid.uuid4()),[bad]).status_code==422; assert sig(p['id'],b['id'])==base
  for field in ('expected_project_revision','expected_node_revision','expected_revision'):
   pp=dict(p); oo=op(n,b)
   if field=='expected_project_revision': pp['revision']+=9
   else: oo[field]+=9
   assert batch(c,h,pp,str(uuid.uuid4()),[oo]).status_code==409; assert sig(p['id'],b['id'])==base
  assert batch(c,h,p,'duplicate',[op(n,b),op(n,b)]).json()['detail']['code']=='DUPLICATE_CONTENT_BLOCK_DELETE'; assert sig(p['id'],b['id'])==base
  new=str(uuid.uuid4()); dependency=[{'op':'create_content_block','id':new,'node_id':n['id'],'expected_node_revision':n['revision'],'content':{}},{'op':'delete_content_block','block_id':new,'expected_revision':1,'expected_node_revision':n['revision']}]
  r=batch(c,h,p,'dependency',dependency); assert r.status_code==422 and r.json()['detail']['code']=='NEW_BLOCK_DELETE_UNSUPPORTED'; assert sig(p['id'],b['id'])==base
  missing={**op(n,b),'block_id':ZERO}; assert batch(c,h,p,'missing-delete',[missing]).status_code==404; assert sig(p['id'],b['id'])==base
  # owner-derived scope, not caller supplied
  made=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':n['revision'],'parent_id':n['id'],'title':'other'}).json(); p2=c.get('/api/projects/'+p['id']).json(); denied=grant(c,p['id'],scope=made['id']); base=sig(p['id'],b['id']); assert batch(c,denied,p2,'scope-denied',[op(c.get('/api/nodes/'+n['id']).json(),b)]).status_code==403; assert sig(p['id'],b['id'])==base

def test_mixed_owner_touch_dedup_and_proposal_revalidation():
 with TestClient(app) as c:
  p,n,b=setup(c,'mixed'); h=grant(c,p['id']); ops=[op(n,b),{'op':'update_node','node_id':n['id'],'expected_revision':n['revision'],'fields':{'summary':'mixed'}},{'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision'],'content':{'safe':'yes'}}]
  r=batch(c,h,p,'mixed-owner',ops); assert r.status_code==200,r.text; P,N,B,L,R=arun(snap(p['id'],b['id'])); assert B is None and P.revision==p['revision']+1 and next(x for x in N if x.id==n['id']).revision==n['revision']+1
  p,n,b=setup(c,'proposal'); ph=grant(c,p['id'],'propose'); made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':p['revision'],'idempotency_key':'proposal-delete','title':'delete','operations':[op(n,b)]}); assert made.status_code==201,made.text
  # Canonical state changes after proposal creation; approval must revalidate and leave pending.
  gui=c.request('DELETE','/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision']}); assert gui.status_code==204
  before=sig(p['id'],b['id']); review=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=hh(),json={'review_note':'stale'}); assert review.status_code in (404,409) and sig(p['id'],b['id'])==before
  async def get():
   async with async_session() as db:return await db.get(AgentProposal,made.json()['proposal_id'])
  row=arun(get()); assert row.status=='pending' and row.reviewed_at is None

def test_post_cas_rollback_gui_agent_proposal(monkeypatch):
 import api.routes as gui, agent_port.service as svc
 original=svc.apply_delete_content_block
 async def explode(db,*a,**kw): await original(db,*a,**kw); raise RuntimeError('after delete')
 monkeypatch.setattr(gui,'apply_delete_content_block',explode); monkeypatch.setattr(svc,'apply_delete_content_block',explode)
 with TestClient(app,raise_server_exceptions=False) as c:
  p,n,b=setup(c,'rb-gui'); before=sig(p['id'],b['id']); assert c.request('DELETE','/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision']}).status_code==500; assert sig(p['id'],b['id'])==before
  p,n,b=setup(c,'rb-agent'); h=grant(c,p['id']); before=sig(p['id'],b['id']); assert batch(c,h,p,'rb-agent',[op(n,b)]).status_code==500; assert sig(p['id'],b['id'])==before
  p,n,b=setup(c,'rb-proposal'); h=grant(c,p['id'],'propose'); made=c.post('/agent/v1/proposals',headers=h,json={'expected_project_revision':p['revision'],'idempotency_key':'rollback-proposal','title':'delete','operations':[op(n,b)]}).json(); before=sig(p['id'],b['id']); assert c.post(f"/api/agent-port/proposals/{made['proposal_id']}/approve",headers=hh(),json={'review_note':'x'}).status_code==500; assert sig(p['id'],b['id'])==before

def test_file_backed_gui_agent_race_three_rounds():
 for i in range(3):
  with TestClient(app) as c:p,n,b=setup(c,f'race-delete-{i}'); h=grant(c,p['id'])
  barrier=Barrier(2)
  def gui():
   with TestClient(app) as c: barrier.wait(); return c.request('DELETE','/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision']}).status_code
  def agent():
   with TestClient(app) as c: barrier.wait(); return batch(c,h,p,f'race-delete-{i}',[op(n,b)]).status_code
  with ThreadPoolExecutor(max_workers=2) as pool: codes=[x.result() for x in (pool.submit(gui),pool.submit(agent))]
  assert sorted(codes)==[204,409],codes; P,N,B,L,R=arun(snap(p['id'],b['id'])); assert B is None and P.revision==p['revision']+1 and next(x for x in N if x.id==n['id']).revision==n['revision']+1 and len([x for x in L if x.action_type=='delete_content_block'])==1
