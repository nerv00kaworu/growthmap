"""Subprocess-isolated acceptance cases for shared canonical create_edge."""
import os, subprocess, sys
from pathlib import Path
BACKEND=Path(__file__).parents[1]
RUNNER=r'''
import asyncio,os,tempfile,uuid
from datetime import datetime,timedelta,timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/edges.db"
os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='isolated-human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,AgentProposal,AgentReceipt,Branch,Edge,Node,Project
HH={'Authorization':'Bearer isolated-human'}
def arun(x):return asyncio.run(x)
def mk(c,name):
 p=c.post('/api/projects',json={'name':name}).json();return p,p['root_node_id']
def node(c,n):return c.get('/api/nodes/'+n).json()
def child(c,p,parent,title):
 a=node(c,parent);pr=c.get('/api/projects/'+p).json()['revision'];r=c.post('/api/projects/'+p+'/nodes',json={'expected_project_revision':pr,'expected_parent_revision':a['revision'],'parent_id':parent,'title':title});assert r.status_code==201,r.text;return r.json()
def gui(c,p,a,b,rel='supports',main=False,**extra):
 return c.post('/api/edges',json={'expected_project_revision':c.get('/api/projects/'+p).json()['revision'],'expected_from_revision':node(c,a)['revision'],'expected_to_revision':node(c,b)['revision'],'from_node_id':a,'to_node_id':b,'relation_type':rel,'is_mainline':main,**extra})
def grant(c,p):
 r=c.post('/api/agent-port/grants',headers=HH,json={'project_id':p,'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'edge','agent_identity':'edge-agent'});assert r.status_code==201,r.text;return {'Authorization':'Bearer '+r.json()['token']}
def batch(c,h,p,key,ops,rev=None):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev or c.get('/api/projects/'+p).json()['revision'],'idempotency_key':key,'operations':ops})
async def state(p):
 async with async_session() as db:
  pr=await db.get(Project,p);ns=(await db.execute(select(Node).where(Node.project_id==p))).scalars().all();es=(await db.execute(select(Edge).where(Edge.project_id==p))).scalars().all();ls=(await db.execute(select(ActionLog).where(ActionLog.project_id==p))).scalars().all();return pr,ns,es,ls

def parity():
 with TestClient(app) as c:
  snaps=[]
  for entry in ('gui','agent'):
   p,r=mk(c,entry);a=child(c,p['id'],r,'a');b=child(c,p['id'],r,'b');before=c.get('/api/projects/'+p['id']).json()['revision']
   if entry=='gui':res=gui(c,p['id'],a['id'],b['id'],note='safe')
   else:
    h=grant(c,p['id']);res=batch(c,h,p['id'],'edge-parity',[{'op':'create_edge','from_node_id':a['id'],'to_node_id':b['id'],'expected_from_revision':node(c,a['id'])['revision'],'expected_to_revision':node(c,b['id'])['revision'],'relation_type':'supports','note':'safe'}])
   assert res.status_code in (200,201),res.text;pr,ns,es,logs=arun(state(p['id']));edge=[e for e in es if e.relation_type=='supports'][0];log=[x for x in logs if x.action_type=='graph_relation_created'];assert pr.revision==before+1 and len(log)==1
   na=next(n for n in ns if n.id==a['id']);nb=next(n for n in ns if n.id==b['id']);assert na.revision==2 and nb.revision==2
   assert set(log[0].payload)<={'edge_id','from_node_id','to_node_id','relation_type','weight','is_mainline','provenance'} and 'token' not in str(log[0].payload).lower()
   assert (log[0].actor_id is None) if entry=='gui' else (log[0].actor_id=='edge-agent')
   snaps.append((edge.relation_type,edge.weight,edge.note,edge.revision,na.revision,nb.revision))
  assert snaps[0]==snaps[1]

def validation():
 with TestClient(app) as c:
  p,r=mk(c,'validation');a=child(c,p['id'],r,'a');b=child(c,p['id'],r,'b');base=c.get('/api/projects/'+p['id']).json()['revision']
  missing=c.post('/api/edges',json={'expected_project_revision':base,'from_node_id':a['id'],'to_node_id':b['id'],'relation_type':'supports'});assert missing.status_code==422
  stale=c.post('/api/edges',json={'expected_project_revision':base,'expected_from_revision':999,'expected_to_revision':node(c,b['id'])['revision'],'from_node_id':a['id'],'to_node_id':b['id'],'relation_type':'supports'});assert stale.status_code==409
  assert c.get('/api/projects/'+p['id']).json()['revision']==base and not [e for e in arun(state(p['id']))[2] if e.relation_type=='supports']
  assert gui(c,p['id'],a['id'],a['id']).status_code==400
  assert gui(c,p['id'],a['id'],b['id'],rel='bogus').status_code==400
  good=gui(c,p['id'],a['id'],b['id']);assert good.status_code==201,good.text;body=good.json();assert (body['authoritative_project_revision'],body['authoritative_from_revision'],body['authoritative_to_revision'])==(base+1,2,2)
  assert gui(c,p['id'],a['id'],b['id']).status_code==409
  # GUI-only mainline demotes and revision-bumps the previous sibling.
  p2,r2=mk(c,'mainline');a2=child(c,p2['id'],r2,'a');b2=child(c,p2['id'],r2,'b');d2=child(c,p2['id'],r2,'d')
  first=gui(c,p2['id'],a2['id'],b2['id'],rel='child_of',main=True);assert first.status_code==201,first.text
  second=gui(c,p2['id'],a2['id'],d2['id'],rel='child_of',main=True);assert second.status_code==201,second.text
  edges=c.get('/api/projects/'+p2['id']+'/edges').json();siblings=[e for e in edges if e['from_node_id']==a2['id'] and e['relation_type']=='child_of']
  assert sum(bool(e['is_mainline']) for e in siblings)==1 and next(e for e in siblings if e['id']==first.json()['id'])['revision']==2
  assert second.json()['touched_edge_revisions']=={first.json()['id']:2}

def batch_contracts():
 with TestClient(app) as c:
  p,r=mk(c,'batch');a=child(c,p['id'],r,'a');b=child(c,p['id'],r,'b');h=grant(c,p['id']);nr=node(c,r)['revision'];ar=node(c,a['id'])['revision'];br=node(c,b['id'])['revision']
  ops=[{'op':'create_edge','from_node_id':a['id'],'to_node_id':b['id'],'expected_from_revision':ar,'expected_to_revision':br,'relation_type':'supports'},{'op':'create_edge','from_node_id':r,'to_node_id':b['id'],'expected_from_revision':nr,'expected_to_revision':br,'relation_type':'references'}]
  res=batch(c,h,p['id'],'dedupe-key',ops);assert res.status_code==200,res.text;receipt=res.json();assert node(c,b['id'])['revision']==br+1 and node(c,a['id'])['revision']==ar+1 and node(c,r)['revision']==nr+1
  replay=batch(c,h,p['id'],'dedupe-key',ops,rev=receipt['project_revision']-1);assert replay.status_code==200 and replay.json()==receipt
  _,_,edges,logs=arun(state(p['id']));assert len([e for e in edges if e.relation_type in ('supports','references')])==2 and len([x for x in logs if x.action_type=='graph_relation_created'])==2
  # Forward-created endpoint remains revision 1 despite the edge.
  p2,r2=mk(c,'forward-key');h2=grant(c,p2['id']);nid=str(uuid.uuid4());ops=[{'op':'create_node','id':nid,'title':'new'},{'op':'create_edge','from_node_id':r2,'to_node_id':nid,'expected_from_revision':1,'expected_to_revision':1,'relation_type':'supports'}]
  out=batch(c,h2,p2['id'],'forward-key',ops);assert out.status_code==200,out.text;assert node(c,nid)['revision']==1 and node(c,r2)['revision']==2

def rollback_contracts():
 import api.routes as gui_routes,agent_port.service as service
 with TestClient(app) as c:
  # GUI post-CAS/post-edge/log fault, including mainline sibling demotion.
  p,r=mk(c,'gui-rollback');a=child(c,p['id'],r,'a');b=child(c,p['id'],r,'b');d=child(c,p['id'],r,'d');first=gui(c,p['id'],a['id'],b['id'],rel='child_of',main=True);assert first.status_code==201
  before=(c.get('/api/projects/'+p['id']).json()['revision'],node(c,a['id'])['revision'],node(c,d['id'])['revision']);original=gui_routes.apply_create_edge
  async def late(*args,**kwargs):
   value=await original(*args,**kwargs);await args[0].flush();assert await args[0].scalar(select(ActionLog.id).where(ActionLog.action_type=='graph_relation_created'));raise RuntimeError('post-edge')
  gui_routes.apply_create_edge=late
  try:
   try:gui(c,p['id'],a['id'],d['id'],rel='child_of',main=True)
   except RuntimeError:pass
  finally:gui_routes.apply_create_edge=original
  pr,ns,es,logs=arun(state(p['id']));assert (pr.revision,next(n for n in ns if n.id==a['id']).revision,next(n for n in ns if n.id==d['id']).revision)==before
  old=next(e for e in es if e.id==first.json()['id']);assert old.is_mainline and old.revision==1 and not any(e.from_node_id==a['id'] and e.to_node_id==d['id'] for e in es);assert len([x for x in logs if x.action_type=='graph_relation_created'])==1
  # Agent direct and proposal faults use the adapter-imported canonical symbol.
  p2,r2=mk(c,'agent-rollback');a2=child(c,p2['id'],r2,'a');h=grant(c,p2['id']);snap=(c.get('/api/projects/'+p2['id']).json()['revision'],node(c,r2)['revision'],node(c,a2['id'])['revision']);op={'op':'create_edge','from_node_id':r2,'to_node_id':a2['id'],'expected_from_revision':snap[1],'expected_to_revision':snap[2],'relation_type':'supports'};original=service.apply_create_edge
  async def agent_late(*args,**kwargs):
   value=await original(*args,**kwargs);await args[0].flush();assert await args[0].scalar(select(ActionLog.id).where(ActionLog.action_type=='graph_relation_created'));raise RuntimeError('post-agent-edge')
  service.apply_create_edge=agent_late
  try:
   try:batch(c,h,p2['id'],'direct-fault', [op])
   except RuntimeError:pass
  finally:service.apply_create_edge=original
  pr,ns,es,logs=arun(state(p2['id']));assert (pr.revision,next(n for n in ns if n.id==r2).revision,next(n for n in ns if n.id==a2['id']).revision)==snap and not [e for e in es if e.relation_type=='supports'] and not [x for x in logs if x.action_type=='graph_relation_created']
  ph=grant(c,p2['id']); # grant wire defaults write; proposal endpoint requires propose, create a dedicated one below
  gp=c.post('/api/agent-port/grants',headers=HH,json={'project_id':p2['id'],'permission':'propose','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'proposal','agent_identity':'edge-proposer'}).json();ph={'Authorization':'Bearer '+gp['token']}
  made=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':snap[0],'idempotency_key':'proposal-create','title':'late edge','operations':[op]});assert made.status_code==201,made.text;pid=made.json()['proposal_id'];service.apply_create_edge=agent_late
  try:
   try:c.post('/api/agent-port/proposals/'+pid+'/approve',headers=HH,json={'review_note':'must rollback'})
   except RuntimeError:pass
  finally:service.apply_create_edge=original
  async def proposal_state():
   async with async_session() as db:
    q=await db.get(AgentProposal,pid);receipts=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p2['id']))).scalars().all();return q,receipts
  q,receipts=arun(proposal_state());assert (q.status,q.reviewed_at,q.review_note or '')==('pending',None,'') and not [x for x in receipts if x.status=='applied'],(q.status,q.reviewed_at,q.review_note,[(x.status,x.action_type) for x in receipts])

def race_and_matrix():
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 with TestClient(app) as c:
  p,r=mk(c,'race');a=child(c,p['id'],r,'a');h=grant(c,p['id']);pr=c.get('/api/projects/'+p['id']).json()['revision'];rr=node(c,r)['revision'];ar=node(c,a['id'])['revision'];bar=Barrier(2)
  def gw():bar.wait();return c.post('/api/edges',json={'expected_project_revision':pr,'expected_from_revision':rr,'expected_to_revision':ar,'from_node_id':r,'to_node_id':a['id'],'relation_type':'supports'})
  def aw():bar.wait();return batch(c,h,p['id'],'race-edge',[{'op':'create_edge','from_node_id':r,'to_node_id':a['id'],'expected_from_revision':rr,'expected_to_revision':ar,'relation_type':'references'}],rev=pr)
  with ThreadPoolExecutor(max_workers=2) as pool:x=pool.submit(gw);y=pool.submit(aw);answers=[x.result(),y.result()]
  assert sum(z.status_code in (200,201) for z in answers)==1 and sum(z.status_code==409 for z in answers)==1,[(z.status_code,z.text) for z in answers];ps,ns,es,logs=arun(state(p['id']));assert ps.revision==pr+1 and next(n for n in ns if n.id==r).revision==rr+1 and next(n for n in ns if n.id==a['id']).revision==ar+1 and len([e for e in es if e.relation_type in ('supports','references')])==1 and len([x for x in logs if x.action_type=='graph_relation_created'])==1
  # Adapter vocabularies and bounds remain distinct; Agent rejects extra is_mainline.
  p2,r2=mk(c,'matrix');a2=child(c,p2['id'],r2,'a');h2=grant(c,p2['id']);assert gui(c,p2['id'],r2,a2['id'],rel='extends').status_code==400
  base={'op':'create_edge','from_node_id':r2,'to_node_id':a2['id'],'expected_from_revision':node(c,r2)['revision'],'expected_to_revision':node(c,a2['id'])['revision']}
  assert batch(c,h2,p2['id'],'extra-main',[{**base,'relation_type':'supports','is_mainline':True}]).status_code==422
  assert batch(c,h2,p2['id'],'gui-vocab',[{**base,'relation_type':'blocks'}]).status_code==422
  assert gui(c,p2['id'],r2,a2['id'],rel='blocks').status_code==201
  p3,r3=mk(c,'agent-wire');a3=child(c,p3['id'],r3,'a');h3=grant(c,p3['id']);wire={'op':'create_edge','from_node_id':r3,'to_node_id':a3['id'],'expected_from_revision':node(c,r3)['revision'],'expected_to_revision':node(c,a3['id'])['revision'],'relation_type':'extends','weight':999,'note':'SECRET_TOKEN_DO_NOT_LOG'};ok=batch(c,h3,p3['id'],'wire-edge', [wire]);assert ok.status_code==200,ok.text;history=c.get('/api/nodes/'+r3+'/history').json();created=[x for x in history if x['action_type']=='graph_relation_created'];assert len(created)==1 and 'SECRET_TOKEN' not in str(created)
  assert gui(c,p3['id'],r3,a3['id'],rel='supports',weight=2).status_code==400
  assert c.post('/api/edges',json={'expected_project_revision':c.get('/api/projects/'+p3['id']).json()['revision'],'expected_from_revision':1,'expected_to_revision':1,'from_node_id':'missing','to_node_id':a3['id'],'relation_type':'supports'}).status_code==400
  # Cross-project and Agent self/duplicate contracts fail before mutation.
  other,other_root=mk(c,'other-project');assert c.post('/api/edges',json={'expected_project_revision':c.get('/api/projects/'+p3['id']).json()['revision'],'expected_from_revision':node(c,r3)['revision'],'expected_to_revision':node(c,other_root)['revision'],'from_node_id':r3,'to_node_id':other_root,'relation_type':'supports'}).status_code==400
  cross={**wire,'to_node_id':other_root,'expected_from_revision':node(c,r3)['revision'],'expected_to_revision':node(c,other_root)['revision'],'relation_type':'references'};before=c.get('/api/projects/'+p3['id']).json()['revision'];assert batch(c,h3,p3['id'],'cross-edge',[cross]).status_code in (403,422) and c.get('/api/projects/'+p3['id']).json()['revision']==before
  selfop={**wire,'to_node_id':r3,'expected_from_revision':node(c,r3)['revision'],'expected_to_revision':node(c,r3)['revision'],'relation_type':'references'};selfres=batch(c,h3,p3['id'],'self-edge',[selfop]);assert selfres.status_code==422 and selfres.json()['detail']['code']=='SELF_RELATION'
  # Explicit distinct branch endpoints reject child_of in both adapters without writes.
  p4,r4=mk(c,'branches');a4=child(c,p4['id'],r4,'a');h4=grant(c,p4['id'])
  async def split_branches():
   async with async_session() as db:
    x=Branch(project_id=p4['id'],name='x',status='active');y=Branch(project_id=p4['id'],name='y',status='active');db.add_all([x,y]);await db.flush();(await db.get(Node,r4)).branch_id=x.id;(await db.get(Node,a4['id'])).branch_id=y.id;await db.commit()
  arun(split_branches());rev=c.get('/api/projects/'+p4['id']).json()['revision'];assert gui(c,p4['id'],a4['id'],r4,rel='child_of').status_code==422
  mismatch={'op':'create_edge','from_node_id':a4['id'],'to_node_id':r4,'expected_from_revision':node(c,a4['id'])['revision'],'expected_to_revision':node(c,r4)['revision'],'relation_type':'child_of'};assert batch(c,h4,p4['id'],'branch-mm',[mismatch]).status_code==422 and c.get('/api/projects/'+p4['id']).json()['revision']==rev

{'parity':parity,'validation':validation,'batch':batch_contracts,'rollback':rollback_contracts,'race':race_and_matrix}[os.environ['CASE']]()
'''
def run(case):
 env={**os.environ,'CASE':case,'PYTHONPATH':str(BACKEND)}
 result=subprocess.run([sys.executable,'-c',RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True)
 assert result.returncode==0,result.stdout+result.stderr
def test_create_edge_shared_parity_isolated():run('parity')
def test_create_edge_gui_validation_and_cas_isolated():run('validation')
def test_create_edge_agent_union_forward_and_replay_isolated():run('batch')
def test_create_edge_post_cas_gui_agent_proposal_rollback_isolated():run('rollback')
def test_create_edge_separate_session_race_and_adapter_matrix_isolated():run('race')
