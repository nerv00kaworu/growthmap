"""Isolated acceptance matrix for the shared canonical create-node primitive."""
import os, subprocess, sys
from pathlib import Path
BACKEND=Path(__file__).parents[1]
RUNNER=r'''
import asyncio,hashlib,json,os,tempfile,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/parity.db"
os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='isolated-human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,Branch,Edge,Node,Project
HH={'Authorization':'Bearer isolated-human'}
def arun(x):return asyncio.run(x)
def project(c,name):
 r=c.post('/api/projects',json={'name':name});assert r.status_code==201,r.text;return r.json()
def grant(c,p,permission='write',**extra):
 r=c.post('/api/agent-port/grants',headers=HH,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'parity','agent_identity':'agent-parity',**extra});assert r.status_code==201,r.text;body=r.json();assert body.get('token'),body;return {'Authorization':'Bearer '+body['token']}
def batch(c,h,p,key,ops):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':p['revision'],'idempotency_key':key,'operations':ops})
async def counts(pid,parent=None):
 async with async_session() as db:
  p=await db.get(Project,pid);n=await db.get(Node,parent) if parent else None
  edges=(await db.execute(select(Edge).where(Edge.project_id==pid))).scalars().all();logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid))).scalars().all();nodes=(await db.execute(select(Node).where(Node.project_id==pid))).scalars().all()
  return p.revision,(n.revision,n.maturity) if n else None,nodes,edges,logs
async def add_branch(pid,status='active'):
 async with async_session() as db:
  b=Branch(project_id=pid,name=status,status=status);db.add(b);await db.commit();return b.id
async def semantic_context(packet):
 # Canonical test helper deliberately removes adapter provenance and generated IDs/timestamps.
 def node(n):return {k:n[k] for k in ('title','summary','node_type','status','maturity','description','tags','priority','confidence','workflow_status','file_paths','branch_id','revision')}
 return {'objective':packet['objective'],'project_revision':packet['project_revision'],'project':{k:packet['project'][k] for k in ('name','description','goal','status','revision')},'target':node(packet['target']),'children':sorted((node(n) for n in packet['children']),key=lambda x:x['title']),'relations':sorted((e['relation_type'],e['is_mainline'],e['revision']) for e in packet['relations'])}
def run_core():
 with TestClient(app) as c:
  # Root parity.
  for entry in ('gui','agent'):
   p=project(c,'root-'+entry)
   if entry=='gui':r=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':1,'title':'rootless'})
   else:r=batch(c,grant(c,p['id']),p,'rootless-1',[{'op':'create_node','title':'rootless'}])
   assert r.status_code in (200,201),r.text;st=arun(counts(p['id']));assert st[0]==2 and len(st[2])==2 and len(st[3])==0
  # Parent containment parity, first/second mainline and exact touches/maturity/history/replay.
  for entry in ('gui','agent'):
   p=project(c,'child-'+entry);root=c.get('/api/nodes/'+p['root_node_id']).json();h=grant(c,p['id']) if entry=='agent' else None
   def create(key,rev,prev):
    if entry=='gui':return c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':rev,'expected_parent_revision':prev,'parent_id':root['id'],'title':key})
    return batch(c,h,{'revision':rev},key+'-key',[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':prev,'title':key}])
   a=create('first',1,1);assert a.status_code in (200,201),a.text
   if entry=='agent':assert create('first',1,1).json()==a.json()
   b=create('second',2,2);assert b.status_code in (200,201),b.text
   rev,parent,nodes,edges,logs=arun(counts(p['id'],root['id']));assert (rev,parent)==(3,(3,'rough'));assert [e.is_mainline for e in edges]==[True,False]
   creates=[x for x in logs if x.action_type=='create_node'];assert len(creates)==2 and len([x for x in logs if x.action_type=='maturity_advance'])==1
   if entry=='gui':assert all(x.actor_id is None for x in creates)

def run_validation():
 with TestClient(app) as c:
  # GUI compatibility uses legacy string details; both adapters reject blank titles.
  p0=project(c,'invalids');h0=grant(c,p0['id']);foreign=project(c,'foreign')
  bad_parent=c.post(f"/api/projects/{p0['id']}/nodes",json={'expected_project_revision':1,'expected_parent_revision':1,'parent_id':foreign['root_node_id'],'title':'x'});assert bad_parent.status_code==400 and bad_parent.json()['detail']=='Invalid parent node',bad_parent.text
  missing_branch=str(uuid.uuid4());bad_branch=c.post(f"/api/projects/{p0['id']}/nodes",json={'expected_project_revision':1,'branch_id':missing_branch,'title':'x'});assert bad_branch.status_code==400 and bad_branch.json()['detail']=='Invalid active branch',bad_branch.text
  assert c.post(f"/api/projects/{p0['id']}/nodes",json={'expected_project_revision':1,'title':'   '}).status_code==422
  assert batch(c,h0,p0,'blank-title',[{'op':'create_node','title':'   '}]).status_code==422
  trimmed=c.post(f"/api/projects/{p0['id']}/nodes",json={'expected_project_revision':1,'title':'  trimmed  '});assert trimmed.status_code==201 and trimmed.json()['title']=='trimmed',trimmed.text
  # Branch inheritance and explicit mismatch.
  p=project(c,'branch');root=c.get('/api/nodes/'+p['root_node_id']).json();bid=arun(add_branch(p['id']))
  async def put_parent():
   async with async_session() as db:n=await db.get(Node,root['id']);n.branch_id=bid;await db.commit()
  arun(put_parent());h=grant(c,p['id']);gui_omitted=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':1,'expected_parent_revision':1,'parent_id':root['id'],'title':'omitted'});assert gui_omitted.status_code==400 and gui_omitted.json()['detail']=='Parent and child must belong to the same branch',gui_omitted.text;gui_explicit=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':1,'expected_parent_revision':1,'parent_id':root['id'],'branch_id':bid,'title':'explicit'});assert gui_explicit.status_code==201,gui_explicit.text;p=c.get('/api/projects/'+p['id']).json();root=c.get('/api/nodes/'+root['id']).json()
  inherited=batch(c,h,p,'inherit-1',[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':root['revision'],'title':'inherited'}]);assert inherited.status_code==200,inherited.text;assert c.get('/api/nodes/'+inherited.json()['results'][0]['id']).json()['branch_id']==bid
  other=arun(add_branch(p['id']));cur=c.get('/api/projects/'+p['id']).json();parent=c.get('/api/nodes/'+root['id']).json()
  g=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':cur['revision'],'expected_parent_revision':parent['revision'],'parent_id':root['id'],'branch_id':other,'title':'bad'});assert g.status_code==400 and g.json()['detail']=='Parent and child must belong to the same branch',g.text
  a=batch(c,h,cur,'mismatch-1',[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':parent['revision'],'branch_id':other,'title':'bad'}]);assert a.status_code==422,a.text
  # Inactive and cross-project parent.
  inactive=arun(add_branch(p['id'],'archived'));cur=c.get('/api/projects/'+p['id']).json()
  inactive_gui=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':cur['revision'],'branch_id':inactive,'title':'inactive'});assert inactive_gui.status_code==400 and inactive_gui.json()['detail']=='Invalid active branch',inactive_gui.text
  assert batch(c,h,cur,'inactive-1',[{'op':'create_node','branch_id':inactive,'title':'inactive'}]).status_code==422
  p2=project(c,'other');assert c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':cur['revision'],'expected_parent_revision':1,'parent_id':p2['root_node_id'],'title':'cross'}).status_code==400
  assert batch(c,h,cur,'cross-project',[{'op':'create_node','parent_id':p2['root_node_id'],'expected_parent_revision':1,'title':'cross'}]).status_code in (403,422)
  # Caller UUID collision and scoped child.
  collision=batch(c,h,cur,'collision-1',[{'op':'create_node','id':root['id'],'title':'collision'}]);assert collision.status_code==409,collision.text
  sp=project(c,'scoped');sroot=c.get('/api/nodes/'+sp['root_node_id']).json();scoped=grant(c,sp['id'],node_scope_id=sroot['id']);r=batch(c,scoped,sp,'scoped-child',[{'op':'create_node','parent_id':sroot['id'],'expected_parent_revision':sroot['revision'],'title':'scoped'}]);assert r.status_code==200,r.text
  # Forward parent: new parent revision remains 1, first-child mainline, root touched once.
  p=project(c,'forward');root=c.get('/api/nodes/'+p['root_node_id']).json();h=grant(c,p['id']);a=str(uuid.uuid4());b=str(uuid.uuid4());d=str(uuid.uuid4());e=str(uuid.uuid4());ops=[{'op':'create_node','id':b,'parent_id':a,'expected_parent_revision':1,'title':'caller-first'},{'op':'create_node','id':d,'parent_id':a,'expected_parent_revision':1,'title':'caller-second'},{'op':'create_node','id':a,'parent_id':root['id'],'expected_parent_revision':1,'title':'parent'},{'op':'create_node','id':e,'parent_id':a,'expected_parent_revision':1,'title':'caller-third'}];r=batch(c,h,p,'forward-parent',ops);assert r.status_code==200,r.text
  st=arun(counts(p['id'],root['id']));na=c.get('/api/nodes/'+a).json();assert st[0]==2 and st[1]==(2,'rough') and na['revision']==2 and r.json()['results'][2]['revision']==2
  siblings=[x for x in st[3] if x.from_node_id==a];assert len(siblings)==3 and sum(bool(x.is_mainline) for x in siblings)==1;flags={x.to_node_id:bool(x.is_mainline) for x in siblings};assert flags=={b:True,d:False,e:False},flags;assert [x['revision'] for x in r.json()['results']]==[1,1,2,1],r.json()['results'];assert c.get('/api/nodes/'+b).json()['revision']==1

def run_atomic_context():
 with TestClient(app) as c:
  # Prevalidation failure leaves graph/history/maturity/revisions untouched.
  p=project(c,'rollback');root=c.get('/api/nodes/'+p['root_node_id']).json();h=grant(c,p['id']);bad=batch(c,h,p,'late-fail',[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':1,'title':'must rollback'},{'op':'create_content_block','node_id':root['id'],'expected_node_revision':99,'content':{'body':'x'}}]);assert bad.status_code==409,bad.text
  st=arun(counts(p['id'],root['id']));assert st[0]==1 and st[1]==(1,'seed') and len(st[2])==1 and not st[3] and not [x for x in st[4] if x.action_type in ('create_node','maturity_advance','agent_batch_applied')]
  # True post-CAS/apply failure through proposal approval rolls back first create,
  # project claim, canonical logs/maturity and the staged proposal review state.
  import agent_port.service as service
  proposal_grant=grant(c,p['id'],permission='propose');token=proposal_grant['Authorization'].removeprefix('Bearer ')
  made=c.post('/agent/v1/proposals',headers=proposal_grant,json={'idempotency_key':'proposal-late-failure','expected_project_revision':1,'title':'rollback proposal','operations':[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':1,'title':'first staged'},{'op':'create_node','title':'second fails'}]});assert made.status_code==201,made.text
  original_apply=service.apply_create_node;calls=0
  async def fail_second(*args,**kwargs):
   nonlocal calls
   calls+=1
   if calls==2:raise __import__('fastapi').HTTPException(409,{'code':'INJECTED_LATE_FAILURE','message':'forced after first canonical write'})
   return await original_apply(*args,**kwargs)
  service.apply_create_node=fail_second
  try:failed=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=HH,json={'review_note':'must rollback'})
  finally:service.apply_create_node=original_apply
  assert failed.status_code==409,failed.text
  async def proposal_state(proposal_id):
   from models.models import AgentProposal
   async with async_session() as db:return await db.get(AgentProposal,proposal_id)
  row=arun(proposal_state(made.json()['proposal_id']));assert row.status=='pending' and row.review_note=='' and row.reviewed_at is None
  st=arun(counts(p['id'],root['id']));assert st[0]==1 and st[1]==(1,'seed') and len(st[2])==1 and not st[3] and not [x for x in st[4] if x.action_type in ('create_node','maturity_advance','agent_batch_applied')]
  # Same expected project/parent race: exactly one winner, loser 409.
  from threading import Barrier
  barrier=Barrier(2)
  def writer(i):barrier.wait();return batch(c,h,p,'race-key-'+str(i),[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':1,'title':'race'}])
  with ThreadPoolExecutor(max_workers=2) as pool:rs=[pool.submit(writer,i) for i in range(2)];rs=[x.result() for x in rs]
  assert sorted(x.status_code for x in rs)==[200,409],[(x.status_code,x.text) for x in rs]
  # Context semantic canonicalization is equal despite actor/receipt/generated-id wire differences.
  packets=[];raw_digests=[]
  for entry in ('gui','agent'):
   q=project(c,'context');rt=c.get('/api/nodes/'+q['root_node_id']).json();gh=grant(c,q['id'])
   if entry=='gui':r=c.post(f"/api/projects/{q['id']}/nodes",json={'expected_project_revision':1,'expected_parent_revision':1,'parent_id':rt['id'],'title':'same'})
   else:r=batch(c,gh,q,'context-create',[{'op':'create_node','parent_id':rt['id'],'expected_parent_revision':1,'title':'same'}])
   assert r.status_code in (200,201),r.text;packet=c.get(f"/agent/v1/context/{rt['id']}?objective=ship",headers=gh).json();assert len(packet['snapshot_digest'])==64;raw_digests.append(packet['snapshot_digest']);packets.append(arun(semantic_context(packet)))
  assert raw_digests[0]!=raw_digests[1]  # source attribution is intentionally digest-visible
  assert packets[0]==packets[1],(packets[0],packets[1]);digests=[hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest() for x in packets];assert digests[0]==digests[1]
case=os.environ['CASE'];{'core':run_core,'validation':run_validation,'atomic_context':run_atomic_context}[case]()
'''
def run(case):
 env={**os.environ,'CASE':case,'PYTHONPATH':str(BACKEND)}
 result=subprocess.run([sys.executable,'-c',RUNNER],env=env,text=True,capture_output=True,cwd=BACKEND)
 assert result.returncode==0,result.stdout+result.stderr
def test_create_node_core_parity_isolated():run('core')
def test_create_node_validation_matrix_isolated():run('validation')
def test_create_node_atomicity_race_and_context_isolated():run('atomic_context')
