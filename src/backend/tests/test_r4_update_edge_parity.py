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
