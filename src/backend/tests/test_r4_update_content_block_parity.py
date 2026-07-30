"""File-backed focused acceptance for shared update_content_block."""
import asyncio, os, tempfile
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
os.environ.setdefault("DATABASE_URL",f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/update-block.db")
os.environ.setdefault("APP_ENV","test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN","update-block-human")
from main import app
from db.database import async_session
from models.models import ActionLog,ContentBlock,Node,Project,AgentReceipt
def human_headers(): return {"Authorization":"Bearer "+(os.environ.get("GROWTHMAP_SESSION_TOKEN") or os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"])}
def setup(c):
 p=c.post('/api/projects',json={'name':'update-block'}).json(); n=c.get('/api/nodes/'+p['root_node_id']).json()
 b=c.post(f"/api/nodes/{n['id']}/blocks",json={'expected_project_revision':1,'expected_node_revision':1,'block_type':'legacy','content':['old'],'order_index':-1}).json()
 return c.get('/api/projects/'+p['id']).json(),c.get('/api/nodes/'+n['id']).json(),b
def grant(c,p):
 g=c.post('/api/agent-port/grants',headers=human_headers(),json={'project_id':p,'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'u','agent_identity':'update-agent'}).json();return {'Authorization':'Bearer '+g['token']}
def batch(c,h,p,rev,key,ops):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
async def rows(pid):
 async with async_session() as db:
  p=await db.get(Project,pid); bs=(await db.execute(select(ContentBlock).join(Node).where(Node.project_id==pid))).scalars().all(); ns=(await db.execute(select(Node).where(Node.project_id==pid))).scalars().all(); ls=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid))).scalars().all(); rs=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==pid))).scalars().all();return p,ns,bs,ls,rs
def run(x):return asyncio.run(x)

def test_gui_legacy_authoritative_and_sanitized_history():
 with TestClient(app) as c:
  p,n,b=setup(c); secret='SECRET_token_value'; r=c.patch('/api/blocks/'+b['id'],json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision'],'block_type':'free form','content':[secret,None,3],'order_index':-999})
  assert r.status_code==200,r.text; out=r.json(); assert (out['authoritative_project_revision'],out['authoritative_node_revision'],out['authoritative_block_revision'])==(p['revision']+1,n['revision']+1,b['revision']+1)
  pr,ns,bs,logs,_=run(rows(p['id'])); assert bs[0].content==[secret,None,3] and secret not in str(next(x.payload for x in logs if x.action_type=='update_content_block'))

def test_missing_empty_and_stale_are_no_write():
 with TestClient(app) as c:
  p,n,b=setup(c); before=run(rows(p['id']))
  assert c.patch('/api/blocks/00000000-0000-4000-8000-000000000000',json={'expected_project_revision':1,'expected_node_revision':1,'expected_revision':1,'content':{}}).json()['detail']=='Block not found'
  for body in ({'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':b['revision']},{'expected_project_revision':999,'expected_node_revision':n['revision'],'expected_revision':b['revision'],'content':{}},{'expected_project_revision':p['revision'],'expected_node_revision':999,'expected_revision':b['revision'],'content':{}},{'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'expected_revision':999,'content':{}}): assert c.patch('/api/blocks/'+b['id'],json=body).status_code in (409,422)
  after=run(rows(p['id'])); assert (before[0].revision,[(x.revision,x.content) for x in before[2]],len(before[3]))==(after[0].revision,[(x.revision,x.content) for x in after[2]],len(after[3]))

def test_agent_strict_update_and_exact_replay():
 with TestClient(app) as c:
  p,n,b=setup(c); h=grant(c,p['id']); op={'op':'update_content_block','block_id':b['id'],'expected_revision':1,'expected_node_revision':2,'fields':{'block_type':'paragraph','content':{'body':'safe'},'order_index':2}}
  r=batch(c,h,p['id'],2,'update-block-replay', [op]); assert r.status_code==200,r.text; body=r.json(); assert body['results'][0]['revision']==2 and body['results'][0]['node_revision']==3
  assert batch(c,h,p['id'],2,'update-block-replay',[op]).json()==body; assert len(run(rows(p['id']))[4])==1

def test_agent_schema_matrix_no_mutation():
 with TestClient(app) as c:
  p,n,b=setup(c); h=grant(c,p['id']); base=run(rows(p['id']))
  fields=[{}, {'content':None},{'extra':1},{'block_type':'legacy'},{'content':{str(i):'x' for i in range(101)}},{'content':{'k'*101:'x'}},{'content':{'x':'v'*16385}},{'order_index':-1},{'order_index':100001}]
  for i,f in enumerate(fields):
   op={'op':'update_content_block','block_id':b['id'],'expected_revision':1,'expected_node_revision':2,'fields':f}; assert batch(c,h,p['id'],2,f'bad-update-{i}',[op]).status_code==422
  after=run(rows(p['id'])); assert (base[0].revision,base[2][0].content,len(base[3]),len(base[4]))==(after[0].revision,after[2][0].content,len(after[3]),len(after[4]))

def test_multi_update_union_bumps_once_logs_per_operation():
 with TestClient(app) as c:
  p,n,b=setup(c); h=grant(c,p['id']); ops=[{'op':'update_content_block','block_id':b['id'],'expected_revision':1,'expected_node_revision':2,'fields':{'content':{'body':'one'}}},{'op':'update_content_block','block_id':b['id'],'expected_revision':1,'expected_node_revision':2,'fields':{'order_index':9}}]
  r=batch(c,h,p['id'],2,'multi-update-block',ops); assert r.status_code==200,r.text; out=r.json(); assert [x['revision'] for x in out['results']]==[2,2] and [x['node_revision'] for x in out['results']]==[3,3]
  pr,ns,bs,logs,_=run(rows(p['id'])); assert pr.revision==3 and bs[0].revision==2 and bs[0].order_index==9 and len([x for x in logs if x.action_type=='update_content_block'])==2
