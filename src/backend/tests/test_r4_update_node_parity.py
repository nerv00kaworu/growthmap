"""Subprocess-isolated acceptance matrix for shared canonical update_node."""
import os, subprocess, sys
from pathlib import Path
BACKEND=Path(__file__).parents[1]
RUNNER=r'''
import asyncio,os,tempfile
from datetime import datetime,timedelta,timezone
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/updates.db"
os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='isolated-human'
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,AgentProposal,ContentBlock,Node,Project
HH={'Authorization':'Bearer isolated-human'}
def arun(x): return asyncio.run(x)
def project(c,name):
 r=c.post('/api/projects',json={'name':name});assert r.status_code==201,r.text;return r.json()
def node(c,nid):return c.get('/api/nodes/'+nid).json()
def grant(c,p,permission='write'):
 r=c.post('/api/agent-port/grants',headers=HH,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'updates','agent_identity':'agent-update'});assert r.status_code==201,r.text;return {'Authorization':'Bearer '+r.json()['token']}
def batch(c,h,project_revision,key,ops):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':project_revision,'idempotency_key':key,'operations':ops})
def gui(c,nid,project_revision,node_revision,changes):return c.patch('/api/nodes/'+nid,json={'expected_project_revision':project_revision,'expected_revision':node_revision,**changes})
async def rows(pid,nid):
 async with async_session() as db:
  p=await db.get(Project,pid);n=await db.get(Node,nid);logs=(await db.execute(select(ActionLog).where(ActionLog.node_id==nid).order_by(ActionLog.created_at))).scalars().all();return p,n,logs

def parity_contracts():
 with TestClient(app) as c:
  shared={'title':'  canonical title  ','summary':'a sufficiently rich shared summary','status':'paused','maturity':'stable','priority':7,'confidence':.8,'description':'d','rules_text':'r','constraints_text':'c','examples_text':'e','questions_text':'q','decision_notes':'notes','tags':['x'],'workflow_status':'review','file_paths':['docs/a.md']}
  snapshots=[]
  for entry in ('gui','agent'):
   p=project(c,entry);rid=p['root_node_id'];before=node(c,rid);h=grant(c,p['id'])
   if entry=='gui':r=gui(c,rid,1,1,shared)
   else:r=batch(c,h,1,'parity-update',[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':shared}])
   assert r.status_code==200,(entry,r.text)
   after=node(c,rid);pr,n,logs=arun(rows(p['id'],rid));updates=[x for x in logs if x.action_type=='update_node']
   assert pr.revision==2 and n.revision==2 and n.updated_at.isoformat()!=before['updated_at'] and len(updates)==1,(entry,pr.revision,n.revision,n.updated_at,before['updated_at'],len(updates))
   assert updates[0].payload['changes']=={**shared,'title':'canonical title'},(entry,updates[0].payload['changes'])
   if entry=='gui':assert n.last_edited_by=='human' and updates[0].actor_id is None
   else:assert n.last_edited_by=='agent-update' and updates[0].actor_id=='agent-update',(n.last_edited_by,updates[0].actor_id)
   snapshots.append({k:after[k] for k in shared}|{'revision':after['revision']})
  assert snapshots[0]==snapshots[1]
  # Existing legacy maturity is not validated when omitted.
  p=project(c,'legacy');rid=p['root_node_id']
  async def legacy():
   async with async_session() as db:n=await db.get(Node,rid);n.maturity='growing';await db.commit()
  arun(legacy());r=gui(c,rid,1,1,{'title':'legacy retained'});assert r.status_code==200,r.text

  # Null/empty/omission/list-clear and immutable/extra contracts.
  p=project(c,'validation');rid=p['root_node_id'];h=grant(c,p['id'])
  for field in ('title','tags','confidence'):
   assert gui(c,rid,1,1,{field:None}).status_code==422
   assert batch(c,h,1,'null-'+field,[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{field:None}}]).status_code==422
  assert c.patch('/api/nodes/'+rid,json={'expected_project_revision':1,'expected_revision':1}).status_code==422
  assert batch(c,h,1,'empty-fields',[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{}}]).status_code==422
  assert batch(c,h,1,'agent-extra',[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'node_type':'task'}}]).status_code==422
  good=gui(c,rid,1,1,{'tags':[],'file_paths':[]});assert good.status_code==200 and good.json()['tags']==[] and good.json()['file_paths']==[]
  # GUI-only extras share exactly one complete canonical update log.
  p=project(c,'gui-extra');rid=p['root_node_id'];r=gui(c,rid,1,1,{'summary':'shared','node_type':'task','position_x':4.5,'position_y':-2});assert r.status_code==200,r.text
  _,_,logs=arun(rows(p['id'],rid));updates=[x for x in logs if x.action_type=='update_node'];assert len(updates)==1 and updates[0].payload['changes']=={'summary':'shared','node_type':'task','position_x':4.5,'position_y':-2}

def maturity_and_batches():
 with TestClient(app) as c:
  # Every canonical value accepted by both wire contracts; obsolete Agent values rejected.
  for entry in ('gui','agent'):
   for maturity in ('seed','rough','developing','stable','finalized'):
    p=project(c,f'{entry}-{maturity}');rid=p['root_node_id'];h=grant(c,p['id'])
    r=gui(c,rid,1,1,{'maturity':maturity}) if entry=='gui' else batch(c,h,1,'maturity-'+maturity,[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'maturity':maturity}}])
    assert r.status_code==200,r.text;assert node(c,rid)['maturity']==maturity
  p=project(c,'old-enums');rid=p['root_node_id'];h=grant(c,p['id'])
  for old in ('sprout','growing','mature'):assert batch(c,h,1,'old-'+old,[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'maturity':old}}]).status_code==422
  # Rich summary auto-advances only without manual maturity; status alone does not.
  for changes,want in (({'summary':'this summary is rich enough'},'rough'),({'summary':'this summary is rich enough','maturity':'seed'},'seed'),({'summary':'this summary is rich enough','maturity':'finalized'},'finalized'),({'status':'completed'},'seed')):
   p=project(c,'maturity-rule');rid=p['root_node_id'];r=gui(c,rid,1,1,changes);assert r.status_code==200,r.text;assert node(c,rid)['maturity']==want
  # Repeated order, transaction-level manual win, exact revision/results/log count/replay.
  for ops,want in (([{'summary':'rich enough to advance maturity'},{'maturity':'seed'}],'seed'),([{'maturity':'seed'},{'summary':'rich enough to advance maturity'}],'seed')):
   p=project(c,'repeat');rid=p['root_node_id'];h=grant(c,p['id']);typed=[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':x} for x in ops]
   typed.append({'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'last title'}})
   r=batch(c,h,1,'repeat-key',typed);assert r.status_code==200,r.text;receipt=r.json();assert receipt['project_revision']==2 and {x['revision'] for x in receipt['results']}=={2}
   assert node(c,rid)['revision']==2 and node(c,rid)['maturity']==want and node(c,rid)['title']=='last title'
   _,_,logs=arun(rows(p['id'],rid));assert len([x for x in logs if x.action_type=='update_node'])==3
   replay=batch(c,h,1,'repeat-key',typed);assert replay.status_code==200 and replay.json()==receipt
   _,_,after=arun(rows(p['id'],rid));assert len(after)==len(logs)
  # Mixed update/create-node/edge/block union touches the same existing root once.
  import uuid
  p=project(c,'mixed');rid=p['root_node_id'];h=grant(c,p['id']);child=str(uuid.uuid4());ops=[
   {'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'mixed'}},
   {'op':'create_node','id':child,'parent_id':rid,'expected_parent_revision':1,'title':'child'},
   {'op':'create_edge','from_node_id':rid,'to_node_id':child,'expected_from_revision':1,'expected_to_revision':1,'relation_type':'supports'},
   {'op':'create_content_block','node_id':rid,'expected_node_revision':1,'content':{'body':'x'}}]
  r=batch(c,h,1,'mixed-key',ops);assert r.status_code==200,r.text;assert r.json()['project_revision']==2 and r.json()['results'][0]['revision']==2 and node(c,rid)['revision']==2 and node(c,child)['revision']==1

def history_rollback_race():
 with TestClient(app) as c:
  # A GUI/Agent stale-CAS race has exactly one winner.
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  p=project(c,'gui-agent-race');rid=p['root_node_id'];h=grant(c,p['id']);barrier=Barrier(2)
  def gui_writer():barrier.wait();return gui(c,rid,1,1,{'title':'gui winner'})
  def agent_writer():barrier.wait();return batch(c,h,1,'race-agent-key',[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'agent winner'}}])
  with ThreadPoolExecutor(max_workers=2) as pool:a=pool.submit(gui_writer);b=pool.submit(agent_writer);race=[a.result(),b.result()]
  assert sorted(x.status_code for x in race)==[200,409],[(x.status_code,x.text) for x in race]
  assert node(c,rid)['revision']==2 and c.get('/api/projects/'+p['id']).json()['revision']==2

  # History exposes both adapters; payload is closed and does not include grant token.
  p=project(c,'history');rid=p['root_node_id'];h=grant(c,p['id']);assert gui(c,rid,1,1,{'summary':'gui'}).status_code==200
  assert batch(c,h,2,'history-agent',[{'op':'update_node','node_id':rid,'expected_revision':2,'fields':{'summary':'agent'}}]).status_code==200
  history=c.get('/api/nodes/'+rid+'/history').json();updates=[x for x in history if x['action_type']=='update_node'];assert len(updates)==2
  assert all(set(x['payload'])<= {'changes','provenance'} for x in updates);assert 'Bearer' not in str(updates) and 'token' not in str(updates).lower()
  # Post-CAS second update failure rolls back fields, maturity, revisions and logs.
  import agent_port.service as service
  p=project(c,'rollback');rid=p['root_node_id'];h=grant(c,p['id']);original=service.apply_update_node;calls=0
  async def fail_second(*args,**kwargs):
   nonlocal calls;calls+=1
   if calls==2:raise HTTPException(409,{'code':'INJECTED','message':'late'})
   return await original(*args,**kwargs)
  service.apply_update_node=fail_second
  try:r=batch(c,h,1,'rollback-key',[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'summary':'rich enough for maturity'}},{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'never'}}])
  finally:service.apply_update_node=original
  assert r.status_code==409,r.text;pr,n,logs=arun(rows(p['id'],rid));assert (pr.revision,n.revision,n.title,n.summary,n.maturity)==(1,1,'rollback','','seed');assert not [x for x in logs if x.action_type=='update_node']
  # Same rollback guarantee through proposal; proposal stays pending.
  ph=grant(c,p['id'],'propose');made=c.post('/agent/v1/proposals',headers=ph,json={'idempotency_key':'proposal-wire','expected_project_revision':1,'title':'rollback','operations':[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'summary':'first'}},{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'second'}}]});assert made.status_code==201,made.text
  calls=0;service.apply_update_node=fail_second
  try:approved=c.post('/api/agent-port/proposals/'+made.json()['proposal_id']+'/approve',headers=HH,json={})
  finally:service.apply_update_node=original
  assert approved.status_code==409,approved.text
  async def proposal(pid):
   async with async_session() as db:return await db.get(AgentProposal,pid)
  row=arun(proposal(made.json()['proposal_id']));assert row.status=='pending' and row.reviewed_at is None
  pr,n,logs=arun(rows(p['id'],rid));assert pr.revision==1 and n.revision==1 and not [x for x in logs if x.action_type=='update_node']
  # Trusted old proposal null materialization treats null as omission, but empty is rejected.
  old=[{'op':'update_node','node_id':rid,'expected_revision':1,'fields':{'title':'old proposal','summary':None}}]
  async def store_old():
   async with async_session() as db:
    g=(await db.execute(select(__import__('models.models',fromlist=['AgentGrant']).AgentGrant).where(__import__('models.models',fromlist=['AgentGrant']).AgentGrant.project_id==p['id']))).scalars().first();q=AgentProposal(grant_id=g.id,project_id=p['id'],title='old',operations=old,expected_project_revision=1);db.add(q);await db.commit();return q.id
  oid=arun(store_old());r=c.post('/api/agent-port/proposals/'+oid+'/approve',headers=HH,json={});assert r.status_code==200,r.text;assert node(c,rid)['title']=='old proposal'

case=os.environ['CASE'];{'parity':parity_contracts,'maturity':maturity_and_batches,'history':history_rollback_race}[case]()
'''
def run(case):
 env={**os.environ,'CASE':case,'PYTHONPATH':str(BACKEND)}
 result=subprocess.run([sys.executable,'-c',RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True)
 assert result.returncode==0,result.stdout+result.stderr
def test_update_node_parity_and_wire_contracts_isolated():run('parity')
def test_update_node_maturity_repeated_and_union_touches_isolated():run('maturity')
def test_update_node_history_rollback_and_legacy_proposal_isolated():run('history')
