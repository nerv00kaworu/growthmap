"""Focused shared canonical create_content_block contracts."""
import asyncio, os, tempfile
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
os.environ.setdefault("DATABASE_URL",f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/blocks-parity.db")
os.environ.setdefault("APP_ENV","test");os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN","block-human")
from main import app
from db.database import async_session
from models.models import ActionLog, ContentBlock, Node, Project
def arun(x): return asyncio.run(x)
def setup(c,name):
 p=c.post('/api/projects',json={'name':name}).json();n=c.get('/api/nodes/'+p['root_node_id']).json();return p,n
def grant(c,p,permission='write'):
 token=os.environ.get('GROWTHMAP_SESSION_TOKEN') or os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']
 g=c.post('/api/agent-port/grants',headers={'Authorization':'Bearer '+token},json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'block','agent_identity':'block-agent'}).json();return {'Authorization':'Bearer '+g['token']}
def batch(c,h,p,key,ops,rev): return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
async def rows(p):
 async with async_session() as db:
  return await db.get(Project,p),(await db.execute(select(Node).where(Node.project_id==p))).scalars().all(),(await db.execute(select(ContentBlock).join(Node).where(Node.project_id==p))).scalars().all(),(await db.execute(select(ActionLog).where(ActionLog.project_id==p))).scalars().all()

def test_gui_agent_parity_history_sanitization_and_authoritative_revisions():
 with TestClient(app) as c:
  snapshots=[]
  for entry in ('gui','agent'):
   p,n=setup(c,entry);content={'body':'SECRET_TOKEN_TEXT','title':'safe'}
   if entry=='gui':r=c.post('/api/nodes/'+n['id']+'/blocks',json={'expected_project_revision':p['revision'],'expected_node_revision':n['revision'],'block_type':'paragraph','content':content,'order_index':2})
   else:r=batch(c,grant(c,p['id']),p['id'],'parity-key',[{'op':'create_content_block','node_id':n['id'],'expected_node_revision':n['revision'],'block_type':'paragraph','content':content,'order_index':2}],p['revision'])
   assert r.status_code in (200,201),r.text;pr,ns,bs,ls=arun(rows(p['id']));created=[x for x in ls if x.action_type=='create_content_block'];assert len(bs)==len(created)==1
   log=created[0];assert 'SECRET_TOKEN' not in str(log.payload) and set(log.payload)<={'block_id','node_id','block_type','order_index','content_key_count','provenance'}
   assert (log.actor_type,log.actor_id)==(('human',None) if entry=='gui' else ('agent','block-agent'))
   owner=next(x for x in ns if x.id==n['id']);assert (pr.revision,owner.revision,bs[0].revision)==(p['revision']+1,n['revision']+1,1)
   if entry=='gui':assert (r.json()['authoritative_project_revision'],r.json()['authoritative_node_revision'],r.json()['authoritative_block_revision'])==(pr.revision,owner.revision,1)
   snapshots.append((bs[0].block_type,bs[0].content,bs[0].order_index,bs[0].revision,owner.revision))
  assert snapshots[0]==snapshots[1]

def test_validation_stale_dedupe_forward_and_replay_state():
 with TestClient(app) as c:
  p,n=setup(c,'contracts');base=p['revision'];assert c.post('/api/nodes/missing/blocks',json={'expected_project_revision':base,'expected_node_revision':1,'content':{}}).status_code==404
  bad=c.post('/api/nodes/'+n['id']+'/blocks',json={'expected_project_revision':base,'expected_node_revision':999,'content':{}});assert bad.status_code==409 and c.get('/api/projects/'+p['id']).json()['revision']==base
  assert c.post('/api/nodes/'+n['id']+'/blocks',json={'expected_project_revision':base,'expected_node_revision':1,'content':{},'order_index':-1}).status_code==422
  h=grant(c,p['id']);ops=[{'op':'create_content_block','node_id':n['id'],'expected_node_revision':1,'content':{'body':'a'}},{'op':'create_content_block','node_id':n['id'],'expected_node_revision':1,'content':{'body':'b'}}]
  out=batch(c,h,p['id'],'two-key-1',ops,base);assert out.status_code==200,out.text;body=out.json();assert c.get('/api/nodes/'+n['id']).json()['revision']==2
  assert batch(c,h,p['id'],'two-key-1',ops,base).json()==body;assert len(arun(rows(p['id']))[2])==2
  p2,r2=setup(c,'forward-key');h2=grant(c,p2['id']);nid='99999999-9999-4999-8999-999999999999';ops=[{'op':'create_node','id':nid,'parent_id':r2['id'],'expected_parent_revision':1,'title':'owner'},{'op':'create_content_block','node_id':nid,'expected_node_revision':1,'content':{'body':'x'}}]
  q=batch(c,h2,p2['id'],'forward-key',ops,p2['revision']);assert q.status_code==200,q.text;assert c.get('/api/nodes/'+nid).json()['revision']==2 and q.json()['results'][0]['revision']==2
