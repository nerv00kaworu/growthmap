"""One file-backed GUI/Agent/human first-complete integration gate."""
import os, subprocess, sys
from pathlib import Path

BACKEND = Path(__file__).parents[1]
RUNNER = r'''
import asyncio, os, tempfile
from datetime import datetime, timedelta, timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/first-complete.sqlite"
os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human-e2e'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import Project,Node,Edge,ContentBlock,ActionLog,AgentReceipt,AgentProposal,AgentReadback
import agent_port.service as service
H={'Authorization':'Bearer human-e2e'}
def arun(v): return asyncio.run(v)
def auth(token): return {'Authorization':'Bearer '+token}
def project(c,p): return c.get('/api/projects/'+p).json()
def node(c,n): return c.get('/api/nodes/'+n).json()
def grant(c,p,permission='write',**scope):
 r=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'first-complete','agent_identity':'integration-agent',**scope});assert r.status_code==201,r.text;return r.json()
def frozen_value(v):
 if hasattr(v,'isoformat'): return v.isoformat()
 if isinstance(v,(dict,list,str,int,float,bool)) or v is None:return v
 return str(v)
async def snapshot(p):
 async with async_session() as db:
  tables=[]
  for model,where,order in [(Project,Project.id==p,Project.id),(Node,Node.project_id==p,Node.id),(Edge,Edge.project_id==p,Edge.id),(ActionLog,ActionLog.project_id==p,ActionLog.id),(AgentReceipt,AgentReceipt.project_id==p,AgentReceipt.id),(AgentProposal,AgentProposal.project_id==p,AgentProposal.id),(AgentReadback,AgentReadback.project_id==p,AgentReadback.id)]:
   rows=(await db.execute(select(model).where(where).order_by(order))).scalars().all();tables.append([{k:frozen_value(v) for k,v in sorted(x.__dict__.items()) if not k.startswith('_')} for x in rows])
  ids=[x['id'] for x in tables[1]];blocks=(await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(ids)).order_by(ContentBlock.id))).scalars().all();tables.insert(3,[{k:frozen_value(v) for k,v in sorted(x.__dict__.items()) if not k.startswith('_')} for x in blocks])
  return tables
with TestClient(app) as c:
 # GUI REST owns the canonical setup: project, nodes, explicit edge and content block.
 made=c.post('/api/projects',json={'name':'First complete integration'});assert made.status_code==201,made.text;p=made.json()['id'];root=made.json()['root_node_id']
 r=node(c,root);child=c.post('/api/projects/'+p+'/nodes',json={'expected_project_revision':project(c,p)['revision'],'expected_parent_revision':r['revision'],'parent_id':root,'title':'Integration target'});assert child.status_code==201,child.text;target=child.json()['id']
 r=node(c,root);t=node(c,target);edge=c.post('/api/edges',json={'expected_project_revision':project(c,p)['revision'],'expected_from_revision':r['revision'],'expected_to_revision':t['revision'],'from_node_id':root,'to_node_id':target,'relation_type':'supports'});assert edge.status_code==201,edge.text;e=edge.json()
 t=node(c,target);block=c.post('/api/nodes/'+target+'/blocks',json={'expected_project_revision':project(c,p)['revision'],'expected_node_revision':t['revision'],'block_type':'paragraph','content':{'text':'GUI seed'},'order_index':0});assert block.status_code==201,block.text
 # Scoped context supplies revision+digest; proposal itself is no-write, human approval changes canon/history.
 propose=grant(c,p,'propose',branch_root_id=root);ph=auth(propose['token']);ctx=c.get('/agent/v1/context/'+target+'?objective=ship',headers=ph);assert ctx.status_code==200,ctx.text;ctx=ctx.json();assert ctx['project_revision']==project(c,p)['revision'] and len(ctx['snapshot_digest'])==64
 before=arun(snapshot(p));proposal=c.post('/agent/v1/proposals',headers=ph,json={'expected_project_revision':ctx['project_revision'],'idempotency_key':'first-proposal','target_node_id':target,'title':'review edge','operations':[{'op':'update_edge','edge_id':e['id'],'expected_revision':e['revision'],'fields':{'note':'approved by human'}}]});assert proposal.status_code==201,proposal.text;pending=arun(snapshot(p));assert pending[0:4]==before[0:4] and pending[6][-1]['status']=='pending'
 approved=c.post('/api/agent-port/proposals/'+proposal.json()['proposal_id']+'/approve',headers=H,json={'review_note':'approved'});assert approved.status_code==200,approved.text;assert next(x for x in c.get('/api/projects/'+p+'/edges').json() if x['id']==e['id'])['note']=='approved by human';assert len(arun(snapshot(p))[4])>len(before[4]) and arun(snapshot(p))[6][-1]['status']=='approved'
 # Human rN->rN+1 wins; stale Agent batch is an atomic 409 and context digest changes.
 write=grant(c,p,'write',branch_root_id=root);wh=auth(write['token']);old=c.get('/agent/v1/context/'+target+'?objective=ship',headers=wh).json();t=node(c,target);human=c.patch('/api/nodes/'+target,json={'expected_project_revision':old['project_revision'],'expected_revision':t['revision'],'summary':'human immediate'});assert human.status_code==200,human.text
 before_stale=arun(snapshot(p));stale_batch=c.post('/agent/v1/batch',headers=wh,json={'expected_project_revision':old['project_revision'],'idempotency_key':'old-agent-batch','operations':[{'op':'update_node','node_id':target,'expected_revision':t['revision'],'fields':{'summary':'must not overwrite'}}]});assert stale_batch.status_code==409 and arun(snapshot(p))==before_stale and node(c,target)['summary']=='human immediate'
 fresh=c.get('/agent/v1/context/'+target+'?objective=ship',headers=wh).json();assert fresh['project_revision']==old['project_revision']+1 and fresh['snapshot_digest']!=old['snapshot_digest']
 # Same key/payload replays exact receipt; mismatch conflicts without writes.
 current=node(c,target);body={'expected_project_revision':fresh['project_revision'],'idempotency_key':'stable-receipt','operations':[{'op':'update_node','node_id':target,'expected_revision':current['revision'],'fields':{'description':'agent canonical write'}}]};one=c.post('/agent/v1/batch',headers=wh,json=body);two=c.post('/agent/v1/batch',headers=wh,json=body);assert one.status_code==two.status_code==200 and one.json()==two.json();after_replay=arun(snapshot(p));mismatch={**body,'operations':[{**body['operations'][0],'fields':{'description':'different'}}]};assert c.post('/agent/v1/batch',headers=wh,json=mismatch).status_code==409 and arun(snapshot(p))==after_replay
 # Implementation ledger is revision-neutral and complete/current; same provenance becomes stale after human mutation.
 provenance=c.get('/agent/v1/context/'+target+'?objective=ship',headers=wh).json();revision=project(c,p)['revision'];rb={'target_node_id':target,'based_on_project_revision':revision,'context_snapshot_digest':provenance['snapshot_digest'],'objective':'ship','summary':'implementation complete','commit_refs':['abc123'],'files':['src/feature.py'],'tests':[{'name':'integration','status':'passed'}],'decisions':['reuse strict v1 wire'],'risks':['packaged platform availability'],'todos':['fresh review'],'evidence':[{'name':'diff','status':'verified','detail':'clean'}]}
 current_rb=c.post('/agent/v1/readbacks',headers=wh,json={'idempotency_key':'readback-current',**rb});assert current_rb.status_code==201,current_rb.text;assert current_rb.json()['context_stale'] is False and project(c,p)['revision']==revision
 t=node(c,target);assert c.patch('/api/nodes/'+target,json={'expected_project_revision':revision,'expected_revision':t['revision'],'rules_text':'human changed again'}).status_code==200
 stale_rb=c.post('/agent/v1/readbacks',headers=wh,json={'idempotency_key':'readback-stale',**rb});assert stale_rb.status_code==201 and stale_rb.json()['context_stale'] is True
 activity=c.get('/api/agent-port/activity?project_id='+p,headers=H).json();rows={x['summary']:x for x in activity['readbacks']};row=rows['implementation complete'];assert row['commit_refs']==['abc123'] and row['files']==['src/feature.py'] and row['tests'][0]['status']=='passed' and row['decisions'] and row['risks'] and row['todos'] and row['evidence']
 # Node/project/branch scope and revocation fail closed.
 exact=grant(c,p,'write',node_scope_id=root);xh=auth(exact['token']);pr=project(c,p)['revision'];assert c.post('/agent/v1/batch',headers=xh,json={'expected_project_revision':pr,'idempotency_key':'node-scope-denied','operations':[{'op':'update_node','node_id':target,'expected_revision':node(c,target)['revision'],'fields':{'title':'denied'}}]}).status_code==403
 other=c.post('/api/projects',json={'name':'other'}).json();assert c.get('/agent/v1/context/'+other['root_node_id'],headers=wh).status_code in (403,404)
 assert c.post('/api/agent-port/grants/'+write['id']+'/revoke',headers=H).status_code==200;assert c.get('/agent/v1/project',headers=wh).status_code==401
 # Stale proposal approval stays pending and creates no history/receipt.
 sh=auth(grant(c,p,'propose',branch_root_id=root)['token']);pr=project(c,p)['revision'];ed=next(x for x in c.get('/api/projects/'+p+'/edges').json() if x['id']==e['id']);sp=c.post('/agent/v1/proposals',headers=sh,json={'expected_project_revision':pr,'idempotency_key':'stale-proposal','title':'stale','operations':[{'op':'update_edge','edge_id':e['id'],'expected_revision':ed['revision'],'fields':{'note':'never'}}]}).json();assert c.patch('/api/edges/'+e['id'],json={'expected_project_revision':pr,'expected_revision':ed['revision'],'note':'human winner'}).status_code==200
 pre=arun(snapshot(p));assert c.post('/api/agent-port/proposals/'+sp['proposal_id']+'/approve',headers=H,json={'review_note':'stale'}).status_code==409;post=arun(snapshot(p));assert pre==post and next(x for x in post[6] if x['id']==sp['proposal_id'])['status']=='pending' and not [x for x in post[5] if x['idempotency_key']=='proposal:'+sp['proposal_id']]
 # A fault injected after canonical history flush rolls every table back exactly.
 wh2=auth(grant(c,p,'write',branch_root_id=root)['token']);pr=project(c,p)['revision'];ed=next(x for x in c.get('/api/projects/'+p+'/edges').json() if x['id']==e['id']);pre=arun(snapshot(p));original=service.apply_update_edge
 async def late(*args,**kwargs):
  out=await original(*args,**kwargs);await args[0].flush();assert await args[0].scalar(select(ActionLog.id).where(ActionLog.project_id==p));raise RuntimeError('injected late fault')
 service.apply_update_edge=late
 try:
  try:c.post('/agent/v1/batch',headers=wh2,json={'expected_project_revision':pr,'idempotency_key':'late-fault','operations':[{'op':'update_edge','edge_id':e['id'],'expected_revision':ed['revision'],'fields':{'note':'rollback'}}]})
  except RuntimeError as error:assert str(error)=='injected late fault'
 finally:service.apply_update_edge=original
 assert arun(snapshot(p))==pre
'''

def test_first_complete_file_backed_integration_gate():
    env={**os.environ,'PYTHONPATH':str(BACKEND)}
    result=subprocess.run([sys.executable,'-c',RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
