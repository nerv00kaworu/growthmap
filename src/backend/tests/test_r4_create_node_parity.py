"""Canonical create-node parity across GUI REST and Agent Port adapters."""
import asyncio,os,tempfile
os.environ.setdefault("DATABASE_URL",f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/node-parity.db")
os.environ.setdefault("APP_ENV","test")
os.environ.setdefault("GROWTHMAP_HUMAN_CONTROL_TOKEN","human-test")
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,Edge,Node,Project
H={"Authorization":"Bearer human-test"}
def arun(c):return asyncio.run(c)
def grant(c,p):return c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'node parity','agent_identity':'agent-parity'}).json()
async def state(pid,parent):
 async with async_session() as db:
  p=await db.get(Project,pid);n=await db.get(Node,parent);edges=(await db.execute(select(Edge).where(Edge.project_id==pid,Edge.from_node_id==parent))).scalars().all();logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid,ActionLog.action_type.in_(['create_node','maturity_advance'])))).scalars().all();return p.revision,n.revision,n.maturity,[(e.relation_type,bool(e.is_mainline)) for e in edges],[(x.action_type,x.actor_type) for x in logs]
def test_gui_agent_create_share_containment_maturity_and_history():
 with TestClient(app) as c:
  out=[]
  for entry in ('gui','agent'):
   p=c.post('/api/projects',json={'name':entry}).json();root=c.get(f"/api/nodes/{p['root_node_id']}").json()
   if entry=='gui':r=c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':root['revision'],'parent_id':root['id'],'title':'child'})
   else:
    g=grant(c,p['id']);r=c.post('/agent/v1/batch',headers={'Authorization':'Bearer '+g['token']},json={'expected_project_revision':p['revision'],'idempotency_key':'node-parity','operations':[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':root['revision'],'title':'child'}]})
   assert r.status_code in (200,201),r.text;out.append(arun(state(p['id'],root['id'])))
  # Actor is adapter provenance; canonical graph/revisions/maturity/action kinds match.
  assert out[0][:4]==out[1][:4]==(2,2,'rough',[('child_of',True)])
  assert sorted(x[0] for x in out[0][4])==sorted(x[0] for x in out[1][4])==['create_node','maturity_advance']
def test_second_child_not_mainline_and_agent_replay_is_exact():
 with TestClient(app) as c:
  p=c.post('/api/projects',json={'name':'replay'}).json();root=c.get(f"/api/nodes/{p['root_node_id']}").json();g=grant(c,p['id']);h={'Authorization':'Bearer '+g['token']}
  def body(key,rev,parent_rev):return {'expected_project_revision':rev,'idempotency_key':key,'operations':[{'op':'create_node','parent_id':root['id'],'expected_parent_revision':parent_rev,'title':key}]}
  a=c.post('/agent/v1/batch',headers=h,json=body('first-key',1,1));assert a.status_code==200;a2=c.post('/agent/v1/batch',headers=h,json=body('first-key',1,1));assert a2.json()==a.json()
  b=c.post('/agent/v1/batch',headers=h,json=body('second-key',2,2));assert b.status_code==200,b.text
  st=arun(state(p['id'],root['id']));assert st[:4]==(3,3,'rough',[('child_of',True),('child_of',False)])
