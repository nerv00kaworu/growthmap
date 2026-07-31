"""Focused shared update_edge acceptance: GUI/Agent parity, union CAS and security."""
import os,subprocess,sys
from pathlib import Path
BACKEND=Path(__file__).parents[1]
RUNNER=r'''
import asyncio,os,tempfile
from datetime import datetime,timedelta,timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/u.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,Edge,Node,Project
H={'Authorization':'Bearer human'}
def arun(x):return asyncio.run(x)
def setup(c,name):
 p=c.post('/api/projects',json={'name':name}).json();root=p['root_node_id'];r=c.get('/api/nodes/'+root).json();pr=c.get('/api/projects/'+p['id']).json()['revision'];n=c.post('/api/projects/'+p['id']+'/nodes',json={'expected_project_revision':pr,'expected_parent_revision':r['revision'],'parent_id':root,'title':'n'}).json();pr=c.get('/api/projects/'+p['id']).json()['revision'];r=c.get('/api/nodes/'+root).json();n=c.get('/api/nodes/'+n['id']).json();e=c.post('/api/edges',json={'expected_project_revision':pr,'expected_from_revision':r['revision'],'expected_to_revision':n['revision'],'from_node_id':root,'to_node_id':n['id'],'relation_type':'supports'}).json();return p['id'],root,n['id'],e

def grant(c,p,permission='write'):
 x=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'u','agent_identity':'a'}).json();return {'Authorization':'Bearer '+x['token']}
def batch(c,h,p,key,ops,rev=None):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev or c.get('/api/projects/'+p).json()['revision'],'idempotency_key':key,'operations':ops})
async def snap(p,e):
 async with async_session() as db:
  pr=await db.get(Project,p);ed=await db.get(Edge,e);ns=(await db.execute(select(Node).where(Node.project_id==p))).scalars().all();logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==p,ActionLog.action_type=='graph_relation_updated'))).scalars().all();return pr,ed,ns,logs
with TestClient(app) as c:
 states=[]
 for mode in ('gui','agent'):
  p,a,b,e=setup(c,mode);before=c.get('/api/projects/'+p).json()['revision'];er=e['revision'];node_revs={x['id']:x['revision'] for x in c.get('/api/nodes/'+a+'/subtree').json().get('children',[])};node_revs[a]=c.get('/api/nodes/'+a).json()['revision'];node_revs[b]=c.get('/api/nodes/'+b).json()['revision']
  if mode=='gui':out=c.patch('/api/edges/'+e['id'],json={'expected_project_revision':before,'expected_revision':er,'weight':.5,'note':'SECRET'})
  else:out=batch(c,grant(c,p),p,'agent-update',[{'op':'update_edge','edge_id':e['id'],'expected_revision':er,'fields':{'weight':.5,'note':'SECRET'}}],before)
  assert out.status_code==200,out.text;pr,ed,ns,logs=arun(snap(p,e['id']));assert pr.revision==before+1 and ed.revision==er+1 and {n.id:n.revision for n in ns}==node_revs;assert len(logs)==1 and 'SECRET' not in str(logs[0].payload);states.append((ed.weight,ed.note,ed.revision))
  if mode=='gui':assert out.json()['authoritative_project_revision']==pr.revision and out.json()['authoritative_edge_revision']==ed.revision==out.json()['revision']
 assert states[0]==states[1]
 # same edge multiple operations: pre-batch CAS union, one touch, ordered writes.
 p,a,b,e=setup(c,'union');h=grant(c,p);pr=c.get('/api/projects/'+p).json()['revision'];ops=[{'op':'update_edge','edge_id':e['id'],'expected_revision':1,'fields':{'note':'first','weight':-2}},{'op':'update_edge','edge_id':e['id'],'expected_revision':1,'fields':{'note':'last'}}];out=batch(c,h,p,'union-update',ops,pr);assert out.status_code==200,out.text;assert [x['revision'] for x in out.json()['results']]==[2,2];_,ed,_,logs=arun(snap(p,e['id']));assert (ed.note,ed.weight,ed.revision)==('last',-2,2) and len(logs)==2
 replay=batch(c,h,p,'union-update',ops,pr);assert replay.json()==out.json();bad=batch(c,h,p,'union-update',[*ops,{'op':'update_edge','edge_id':e['id'],'expected_revision':2,'fields':{'note':'x'}}],pr);assert bad.status_code==409
 # immutable/strict wire and create-update dependency fail before project CAS.
 base=c.get('/api/projects/'+p).json()['revision'];assert batch(c,h,p,'extra-key',[{'op':'update_edge','edge_id':e['id'],'expected_revision':2,'fields':{'note':'x','from_node_id':a}}],base).status_code==422
 made='11111111-1111-4111-8111-111111111111';ar=c.get('/api/nodes/'+a).json()['revision'];br=c.get('/api/nodes/'+b).json()['revision'];dep=[{'op':'create_edge','id':made,'from_node_id':a,'to_node_id':b,'expected_from_revision':ar,'expected_to_revision':br,'relation_type':'references'},{'op':'update_edge','edge_id':made,'expected_revision':1,'fields':{'note':'x'}}];z=batch(c,h,p,'dependency-key',dep,base);assert z.status_code==422 and z.json()['detail']['code']=='NEW_EDGE_UPDATE_UNSUPPORTED' and c.get('/api/projects/'+p).json()['revision']==base
'''
def test_update_edge_shared_acceptance_isolated():
 env={**os.environ,'PYTHONPATH':str(BACKEND)};r=subprocess.run([sys.executable,'-c',RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr

MATRIX_RUNNER=r'''
import asyncio,os,tempfile,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from threading import Barrier
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/matrix.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,AgentProposal,AgentReceipt,Edge,Node,Project
import api.routes as gui_routes,agent_port.service as service
H={'Authorization':'Bearer human'}
def arun(x):return asyncio.run(x)
def mk(c,name):
 p=c.post('/api/projects',json={'name':name}).json();r=p['root_node_id'];rr=c.get('/api/nodes/'+r).json();n=c.post('/api/projects/'+p['id']+'/nodes',json={'expected_project_revision':p['revision'],'expected_parent_revision':rr['revision'],'parent_id':r,'title':'n'}).json();rr=c.get('/api/nodes/'+r).json();n=c.get('/api/nodes/'+n['id']).json();pr=c.get('/api/projects/'+p['id']).json()['revision'];e=c.post('/api/edges',json={'expected_project_revision':pr,'expected_from_revision':rr['revision'],'expected_to_revision':n['revision'],'from_node_id':r,'to_node_id':n['id'],'relation_type':'supports'}).json();return p['id'],r,n['id'],e
def grant(c,p,permission='write',**scope):
 x=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'u','agent_identity':'agent',**scope});assert x.status_code==201,x.text;return {'Authorization':'Bearer '+x.json()['token']},x.json()
def op(e,**fields):return {'op':'update_edge','edge_id':e['id'],'expected_revision':e['revision'],'fields':fields or {'note':'updated'}}
def batch(c,h,p,key,ops,rev=None):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev or c.get('/api/projects/'+p).json()['revision'],'idempotency_key':key,'operations':ops})
async def state(p,eid,pid=None):
 async with async_session() as db:
  pr=await db.get(Project,p);e=await db.get(Edge,eid);logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==p,ActionLog.action_type=='graph_relation_updated'))).scalars().all();proposal=await db.get(AgentProposal,pid) if pid else None;receipts=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p))).scalars().all();return pr,e,logs,proposal,receipts
with TestClient(app) as c:
 # Proposal persists no canonical write, approval applies; stale approval leaves pending.
 p,a,b,e=mk(c,'proposal');ph,_=grant(c,p,'propose');rev=c.get('/api/projects/'+p).json()['revision'];made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':rev,'idempotency_key':'proposal-good','title':'edge','operations':[op(e,note='proposal-secret')]});assert made.status_code==201,made.text;pid=made.json()['proposal_id'];pr,ed,logs,q,_=arun(state(p,e['id'],pid));assert pr.revision==rev and ed.note=='' and not logs and q.status=='pending';approved=c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'ok'});assert approved.status_code==200,approved.text;pr,ed,logs,q,_=arun(state(p,e['id'],pid));assert ed.note=='proposal-secret' and ed.revision==2 and q.status=='approved' and 'proposal-secret' not in str(logs[0].payload)
 p,a,b,e=mk(c,'proposal-stale');ph,_=grant(c,p,'propose');rev=c.get('/api/projects/'+p).json()['revision'];made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':rev,'idempotency_key':'proposal-stale','title':'edge','operations':[op(e)]});pid=made.json()['proposal_id'];c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'note':'winner'});stale=c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'stale'});assert stale.status_code==409;pr,ed,logs,q,receipts=arun(state(p,e['id'],pid));assert q.status=='pending' and q.reviewed_at is None and ed.note=='winner' and not [x for x in receipts if x.idempotency_key=='proposal:'+pid]
 # Post-history injected faults rollback GUI, direct Agent and proposal review.
 for mode in ('gui','direct','proposal'):
  p,a,b,e=mk(c,'rollback-'+mode);rev=c.get('/api/projects/'+p).json()['revision'];before=arun(state(p,e['id']))[:2]
  module=gui_routes if mode=='gui' else service;original=module.apply_update_edge
  async def late(*args,**kwargs):
   out=await original(*args,**kwargs);await args[0].flush();assert await args[0].scalar(select(ActionLog.id).where(ActionLog.action_type=='graph_relation_updated'));raise RuntimeError('late')
  module.apply_update_edge=late
  try:
   try:
    if mode=='gui':c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'note':'bad'})
    elif mode=='direct':batch(c,grant(c,p)[0],p,'rollback-direct',[op(e,note='bad')],rev)
    else:
     ph,_=grant(c,p,'propose');made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':rev,'idempotency_key':'rollback-proposal','title':'x','operations':[op(e,note='bad')]});c.post('/api/agent-port/proposals/'+made.json()['proposal_id']+'/approve',headers=H,json={'review_note':'x'})
   except RuntimeError:pass
  finally:module.apply_update_edge=original
  pr,ed,logs,q,receipts=arun(state(p,e['id'],made.json()['proposal_id'] if mode=='proposal' else None));assert pr.revision==before[0].revision and ed.revision==before[1].revision and ed.note==before[1].note and not logs
  if mode=='proposal':assert q.status=='pending' and not [x for x in receipts if x.idempotency_key=='proposal:'+q.id]
 # Three file-backed independent-session GUI/Agent races: exactly one winner.
 for round in range(3):
  p,a,b,e=mk(c,'race'+str(round));rev=c.get('/api/projects/'+p).json()['revision'];h,_=grant(c,p);bar=Barrier(2)
  def gui():bar.wait();return c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'note':'gui'})
  def agent():bar.wait();return batch(c,h,p,'race-key-'+str(round),[op(e,note='agent')],rev)
  with ThreadPoolExecutor(max_workers=2) as pool:x=pool.submit(gui);y=pool.submit(agent);answers=[x.result(),y.result()]
  assert sorted(z.status_code for z in answers)==[200,409],[(z.status_code,z.text) for z in answers];pr,ed,logs,_,_=arun(state(p,e['id']));assert pr.revision==rev+1 and ed.revision==2 and len(logs)==1
 # Persisted endpoint scope: exact-node denies because other endpoint is out; project scope succeeds. Cross-project edge id is hidden/no-write.
 p,a,b,e=mk(c,'scope');h,_=grant(c,p,node_scope_id=a);rev=c.get('/api/projects/'+p).json()['revision'];denied=batch(c,h,p,'scope-denied',[op(e)],rev);assert denied.status_code==403 and c.get('/api/projects/'+p).json()['revision']==rev
 h,_=grant(c,p);assert batch(c,h,p,'scope-good',[op(e)],rev).status_code==200
 other,oa,ob,oe=mk(c,'other');before=c.get('/api/projects/'+p).json()['revision'];cross=batch(c,h,p,'cross-edge',[op(oe)],before);assert cross.status_code==404 and c.get('/api/projects/'+p).json()['revision']==before
 # Adapter bounds and no-write.
 p,a,b,e=mk(c,'bounds');rev=c.get('/api/projects/'+p).json()['revision'];assert c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'weight':1.1}).status_code==400;assert c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'note':'x'*2001}).status_code==400;h,_=grant(c,p);assert batch(c,h,p,'agent-weight',[op(e,weight=1001)],rev).status_code==422;assert batch(c,h,p,'agent-note',[op(e,note='x'*501)],rev).status_code==422;assert c.get('/api/projects/'+p).json()['revision']==rev
 # Both create/update orders reject the same stable code before writes.
 for reverse in (False,True):
  p,a,b,e=mk(c,'dependency'+str(reverse));h,_=grant(c,p);rev=c.get('/api/projects/'+p).json()['revision'];new=str(uuid.uuid4());create={'op':'create_edge','id':new,'from_node_id':a,'to_node_id':b,'expected_from_revision':c.get('/api/nodes/'+a).json()['revision'],'expected_to_revision':c.get('/api/nodes/'+b).json()['revision'],'relation_type':'references'};update={'op':'update_edge','edge_id':new,'expected_revision':1,'fields':{'note':'x'}};ops=[update,create] if reverse else [create,update];out=batch(c,h,p,'dependency-'+str(reverse).lower(),ops,rev);assert out.status_code==422 and out.json()['detail']['code']=='NEW_EDGE_UPDATE_UNSUPPORTED' and c.get('/api/projects/'+p).json()['revision']==rev
'''
def test_update_edge_proposal_rollback_race_scope_bounds_isolated():
 env={**os.environ,'PYTHONPATH':str(BACKEND)};r=subprocess.run([sys.executable,'-c',MATRIX_RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr

EVIDENCE_RUNNER=r'''
import asyncio,os,tempfile,uuid
from datetime import datetime,timedelta,timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/evidence.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,AgentProposal,AgentReceipt,Edge,Project
import api.routes as gui_routes,agent_port.service as service
H={'Authorization':'Bearer human'}
def arun(x):return asyncio.run(x)
def dt(x):return x.isoformat() if x else None
def mk(c,name):
 p=c.post('/api/projects',json={'name':name}).json();a=p['root_node_id'];an=c.get('/api/nodes/'+a).json();b=c.post('/api/projects/'+p['id']+'/nodes',json={'expected_project_revision':p['revision'],'expected_parent_revision':an['revision'],'parent_id':a,'title':'b'}).json()['id'];an=c.get('/api/nodes/'+a).json();bn=c.get('/api/nodes/'+b).json();rev=c.get('/api/projects/'+p['id']).json()['revision'];e=c.post('/api/edges',json={'expected_project_revision':rev,'expected_from_revision':an['revision'],'expected_to_revision':bn['revision'],'from_node_id':a,'to_node_id':b,'relation_type':'supports'}).json();return p['id'],a,b,e
def grant(c,p,permission='write',**scope):
 r=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'e','agent_identity':'agent',**scope});assert r.status_code==201,r.text;return {'Authorization':'Bearer '+r.json()['token']}
def op(e,**fields):return {'op':'update_edge','edge_id':e['id'],'expected_revision':e['revision'],'fields':fields}
def batch(c,h,p,key,ops,rev):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
async def frozen(p,eid):
 async with async_session() as db:
  p1=await db.get(Project,p);e=await db.get(Edge,eid)
  logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==p).order_by(ActionLog.id))).scalars().all();rs=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p).order_by(AgentReceipt.id))).scalars().all();qs=(await db.execute(select(AgentProposal).where(AgentProposal.project_id==p).order_by(AgentProposal.id))).scalars().all()
  return {'project':(p1.id,p1.name,p1.description,p1.goal,p1.status,p1.root_node_id,p1.revision,dt(p1.created_at),dt(p1.updated_at)),'edge':(e.id,e.project_id,e.from_node_id,e.to_node_id,e.relation_type,e.weight,e.note,e.is_mainline,e.revision,dt(e.created_at)),'logs':[(x.id,x.node_id,x.actor_type,x.actor_id,x.action_type,x.payload,dt(x.created_at)) for x in logs],'receipts':[(x.id,x.grant_id,x.idempotency_key,x.request_digest,x.action_type,x.status,x.response,dt(x.created_at)) for x in rs],'proposals':[(x.id,x.grant_id,x.target_node_id,x.status,x.title,x.rationale,x.expected_project_revision,x.operations,x.review_note,dt(x.created_at),dt(x.reviewed_at)) for x in qs]}
with TestClient(app,raise_server_exceptions=True) as c:
 # Every accepted adapter boundary is exercised exactly.
 gui_ok=[{'weight':0},{'weight':1},{'note':'g'*2000}]
 for i,fields in enumerate(gui_ok):
  p,a,b,e=mk(c,'gui-ok'+str(i));rev=c.get('/api/projects/'+p).json()['revision'];r=c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,**fields});assert r.status_code==200,r.text
 agent_ok=[{'weight':-1000},{'weight':1000},{'note':'a'*500}]
 for i,fields in enumerate(agent_ok):
  p,a,b,e=mk(c,'agent-ok'+str(i));rev=c.get('/api/projects/'+p).json()['revision'];r=batch(c,grant(c,p),p,'agent-ok-'+str(i),[op(e,**fields)],rev);assert r.status_code==200,r.text
 # Every rejected bound proves exact no-write across project/edge/all logs/receipts/proposals.
 gui_bad=[{'weight':-0.0001},{'weight':1.0001},{'note':'x'*2001}]
 for i,fields in enumerate(gui_bad):
  p,a,b,e=mk(c,'gui-bad'+str(i));before=arun(frozen(p,e['id']));rev=c.get('/api/projects/'+p).json()['revision'];r=c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,**fields});assert r.status_code==400 and arun(frozen(p,e['id']))==before
 agent_bad=[{'weight':-1000.0001},{'weight':1000.0001},{'note':'x'*501}]
 for i,fields in enumerate(agent_bad):
  p,a,b,e=mk(c,'agent-bad'+str(i));h=grant(c,p);before=arun(frozen(p,e['id']));rev=c.get('/api/projects/'+p).json()['revision'];r=batch(c,h,p,'agent-bad-'+str(i),[op(e,**fields)],rev);assert r.status_code==422 and arun(frozen(p,e['id']))==before
 # Same-edge union: last write wins, one revision, all results final; exact sanitized per-op logs.
 p,a,b,e=mk(c,'same');h=grant(c,p);rev=c.get('/api/projects/'+p).json()['revision'];before=arun(frozen(p,e['id']));secret='REQUEST_SECRET';ops=[op(e,note='FIRST_NOTE',weight=-7),op(e,note='LAST_NOTE')];r=batch(c,h,p,secret+'-key',ops,rev);assert r.status_code==200,r.text;after=arun(frozen(p,e['id']));assert after['edge'][5:9]==(-7,'LAST_NOTE',False,2);assert [x['revision'] for x in r.json()['results']]==[2,2]
 prior_ids={x[0] for x in before['logs']};added=[x for x in after['logs'] if x[0] not in prior_ids];assert len(added)==3;updates=[x for x in added if x[4]=='graph_relation_updated'];assert len(updates)==2;assert sorted((x[5]['provenance']['operation_index'],x[5]['changed_fields']) for x in updates)==[(0,['note','weight']),(1,['note'])];assert all('FIRST_NOTE' not in str(x[5]) and 'LAST_NOTE' not in str(x[5]) and secret not in str(x[5]) for x in updates)
 # Late post-history fault exact rollback. GUI/direct start before request; proposal starts after creation.
 for mode in ('gui','direct','proposal'):
  p,a,b,e=mk(c,'fault-'+mode);rev=c.get('/api/projects/'+p).json()['revision'];module=gui_routes if mode=='gui' else service;original=module.apply_update_edge;pid=None
  if mode=='proposal':
   ph=grant(c,p,'propose');made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':rev,'idempotency_key':'fault-proposal','title':'p','operations':[op(e,note='bad')]});assert made.status_code==201;pid=made.json()['proposal_id']
  before=arun(frozen(p,e['id']))
  async def fault(*args,**kwargs):
   out=await original(*args,**kwargs);await args[0].flush();assert await args[0].scalar(select(ActionLog.id).where(ActionLog.action_type=='graph_relation_updated'));raise RuntimeError('post-history')
  module.apply_update_edge=fault
  try:
   try:
    if mode=='gui':c.patch('/api/edges/'+e['id'],json={'expected_project_revision':rev,'expected_revision':1,'note':'bad'})
    elif mode=='direct':batch(c,grant(c,p),p,'fault-direct',[op(e,note='bad')],rev)
    else:c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'review'})
   except RuntimeError:pass
  finally:module.apply_update_edge=original
  after=arun(frozen(p,e['id']));assert after==before,(mode,before,after)
  if mode=='direct':assert len(after['receipts'])==len(before['receipts'])==0
  if mode=='proposal':assert len(after['receipts'])==len(before['receipts'])==1 and not [x for x in after['receipts'] if x[2]=='proposal:'+pid] and after['proposals'][0][3]=='pending' and after['proposals'][0][-1] is None and after['proposals'][0][8]==''
 # Denials: exact snapshots and stable codes.
 p,a,b,e=mk(c,'scope');h=grant(c,p,node_scope_id=a);before=arun(frozen(p,e['id']));rev=c.get('/api/projects/'+p).json()['revision'];r=batch(c,h,p,'scope-exact',[op(e,note='x')],rev);assert r.status_code==403 and r.json()['detail']['code']=='SCOPE_DENIED' and arun(frozen(p,e['id']))==before
 p,a,b,e=mk(c,'home');h=grant(c,p);other,oa,ob,oe=mk(c,'foreign');before=arun(frozen(p,e['id']));foreign_before=arun(frozen(other,oe['id']));rev=c.get('/api/projects/'+p).json()['revision'];r=batch(c,h,p,'cross-exact',[op(oe,note='x')],rev);assert r.status_code==404 and arun(frozen(p,e['id']))==before and arun(frozen(other,oe['id']))==foreign_before
 codes=[]
 for reverse in (False,True):
  p,a,b,e=mk(c,'dependency-exact'+str(reverse));h=grant(c,p);rev=c.get('/api/projects/'+p).json()['revision'];new=str(uuid.uuid4());create={'op':'create_edge','id':new,'from_node_id':a,'to_node_id':b,'expected_from_revision':c.get('/api/nodes/'+a).json()['revision'],'expected_to_revision':c.get('/api/nodes/'+b).json()['revision'],'relation_type':'references'};update={'op':'update_edge','edge_id':new,'expected_revision':1,'fields':{'note':'secret'}};before=arun(frozen(p,e['id']));r=batch(c,h,p,'dependency-exact-'+str(reverse).lower(),[update,create] if reverse else [create,update],rev);codes.append(r.json()['detail']['code']);assert r.status_code==422 and arun(frozen(p,e['id']))==before
 assert codes==['NEW_EDGE_UPDATE_UNSUPPORTED','NEW_EDGE_UPDATE_UNSUPPORTED']
'''
def test_update_edge_exact_evidence_contract_isolated():
 env={**os.environ,'PYTHONPATH':str(BACKEND)};r=subprocess.run([sys.executable,'-c',EVIDENCE_RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
