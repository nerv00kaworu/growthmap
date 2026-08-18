"""Dedicated dual-entry and proposal atomicity tests for canonical branch copies."""
import asyncio, os, tempfile
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

os.environ["DATABASE_URL"]=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/branch-parity.db"
os.environ.setdefault("APP_ENV","test")
os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"]="human-test"
from main import app
import db.database as database
from models.models import ActionLog,AgentGrant,AgentProposal,AgentReceipt,Branch,ContentBlock,Edge,Node,Project

_state=None
def setup_module():
 global _state
 from tests.r4_harness import setup_r4;_state=setup_r4('branch-parity')
def teardown_module():
 from tests.r4_harness import teardown_r4;teardown_r4(_state)

H={"Authorization":"Bearer human-test"}
SEMANTIC=("title","summary","node_type","status","maturity","priority","confidence","description","rules_text","constraints_text","examples_text","questions_text","decision_notes","tags","workflow_status","file_paths","position_x","position_y","last_edited_by")

def arun(fn): return asyncio.run(fn())
async def seed(project_id,root_id,label):
 async with database.async_session() as db:
  root=await db.get(Node,root_id)
  values=dict(title=f"{label}-root",summary="sum",node_type="decision",status="blocked",maturity="stable",priority=9,confidence=.87,description="desc",rules_text="rules",constraints_text="constraints",examples_text="examples",questions_text="questions",decision_notes="notes",tags=["z",{"nested":True}],workflow_status="approved",file_paths=["src/a.py"],position_x=12.5,position_y=-4,last_edited_by="editor-root")
  for k,v in values.items():setattr(root,k,deepcopy(v))
  child=Node(project_id=project_id,title=f"{label}-child",summary="child summary",node_type="risk",status="active",maturity="growing",priority=4,confidence=.42,description="child desc",rules_text="cr",constraints_text="cc",examples_text="ce",questions_text="cq",decision_notes="cd",tags=["child"],workflow_status="review",file_paths=["b.md"],position_x=2,position_y=3,last_edited_by="editor-child",revision=1)
  grand=Node(project_id=project_id,title=f"{label}-grand",summary="grand summary",node_type="task",status="archived",maturity="seed",priority=1,confidence=.1,description="gd",rules_text="gr",constraints_text="gc",examples_text="ge",questions_text="gq",decision_notes="gn",tags=["grand"],workflow_status="draft",file_paths=["g.txt"],position_x=8,position_y=9,last_edited_by="editor-grand",revision=1)
  outside=Node(project_id=project_id,title=f"{label}-outside",revision=1);db.add_all([child,grand,outside]);await db.flush()
  db.add_all([
   Edge(project_id=project_id,from_node_id=root.id,to_node_id=child.id,relation_type="child_of",weight=.25,note="main",is_mainline=True,revision=1),
   Edge(project_id=project_id,from_node_id=child.id,to_node_id=grand.id,relation_type="child_of",weight=.75,note="side",is_mainline=False,revision=1),
   Edge(project_id=project_id,from_node_id=root.id,to_node_id=grand.id,relation_type="supports",weight=.5,note="do-not-copy",revision=1),
   Edge(project_id=project_id,from_node_id=outside.id,to_node_id=root.id,relation_type="child_of",note="outside-subtree",revision=1),
   ContentBlock(node_id=root.id,block_type="code",content={"deep":{"items":[2,1]}},order_index=9,created_by="seed",revision=1),
   ContentBlock(node_id=root.id,block_type="paragraph",content={"body":"first"},order_index=2,created_by="seed",revision=1),
   ContentBlock(node_id=grand.id,block_type="table",content={"rows":[[1,{"x":2}]]},order_index=4,created_by="seed",revision=1),
  ]);await db.commit()
  return child.id,grand.id,outside.id
async def snapshot(project_id,branch_id=None):
 async with database.async_session() as db:
  p=await db.get(Project,project_id)
  q=select(Node).where(Node.project_id==project_id)
  if branch_id is None:q=q.where(Node.branch_id.is_(None))
  else:q=q.where(Node.branch_id==branch_id)
  nodes=(await db.execute(q)).scalars().all();ids={n.id for n in nodes}
  blocks=(await db.execute(select(ContentBlock).where(ContentBlock.node_id.in_(ids)))).scalars().all() if ids else []
  edges=(await db.execute(select(Edge).where(Edge.from_node_id.in_(ids),Edge.to_node_id.in_(ids)))).scalars().all() if ids else []
  branches=(await db.execute(select(Branch).where(Branch.project_id==project_id))).scalars().all()
  return p,nodes,blocks,edges,branches

def canonical(nodes,blocks,edges,label):
 by={n.id:n.title.removeprefix(label+"-") for n in nodes}
 return {
  "nodes":sorted([{k:deepcopy(getattr(n,k)) for k in SEMANTIC}|{"key":by[n.id]} for n in nodes],key=lambda x:x["key"]),
  "blocks":sorted([(by[b.node_id],b.block_type,deepcopy(b.content),b.order_index,b.revision) for b in blocks],key=repr),
  "edges":sorted([(by[e.from_node_id],by[e.to_node_id],e.relation_type,e.weight,e.note,bool(e.is_mainline),e.revision) for e in edges],key=repr),
 }
def grant(c,pid,permission="write"):
 return c.post('/api/agent-port/grants',headers=H,json={'project_id':pid,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'parity','agent_identity':'agent-copy'}).json()

def test_gui_and_agent_are_true_dual_entry_semantic_parity():
 with TestClient(app) as c:
  outputs=[]
  for entry,label in (("gui","gui"),("agent","agent")):
   p=c.post('/api/projects',json={'name':label}).json();root=p['root_node_id'];child,grand,outside=arun(lambda:seed(p['id'],root,label));before=arun(lambda:snapshot(p['id']))
   bid='44444444-4444-4444-8444-444444444444' if entry=='agent' else None
   if entry=='gui':r=c.post(f"/api/projects/{p['id']}/branches",json={'expected_project_revision':p['revision'],'source_node_id':root,'name':'copy'})
   else:
    g=grant(c,p['id']);r=c.post('/agent/v1/batch',headers={'Authorization':'Bearer '+g['token']},json={'expected_project_revision':p['revision'],'idempotency_key':'dual-entry','operations':[{'op':'create_branch','id':bid,'source_node_id':root,'expected_source_revision':1,'name':'copy'}]})
   assert r.status_code in (200,201),r.text
   if entry=='gui':bid=r.json()['id']
   after_source=arun(lambda:snapshot(p['id']));copied=arun(lambda:snapshot(p['id'],bid));project,nodes,blocks,edges,branches=copied
   assert project.revision==p['revision']+1 and len(branches)==1 and branches[0].revision==1
   assert len(nodes)==3 and len(blocks)==3 and len(edges)==2
   assert all(n.revision==1 and n.branch_id==bid for n in nodes) and all(b.revision==1 for b in blocks) and all(e.revision==1 for e in edges)
   source_ids={n.id for n in before[1]};assert source_ids.isdisjoint({n.id for n in nodes}) and outside not in {n.id for n in nodes}
   assert canonical(before[1],before[2],before[3],label)==canonical(after_source[1],after_source[2],after_source[3],label)
   outputs.append(canonical(nodes,blocks,edges,label))
  # Actor provenance intentionally differs; semantic source fields do not.
  for output in outputs:
   for node in output['nodes']:
    node.pop('last_edited_by')
    node['title']=node['key']
  assert outputs[0]==outputs[1]

def test_proposal_approval_accepts_persistent_null_and_finite_future_and_is_idempotent():
 with TestClient(app) as c:
  for mode in ("persistent","finite-naive","finite-aware"):
   p=c.post('/api/projects',json={'name':mode}).json();arun(lambda:seed(p['id'],p['root_node_id'],mode))
   grant_body={'project_id':p['id'],'permission':'propose','label':mode,'agent_identity':'approval-regression'}
   if mode=='persistent':grant_body.update(persistent=True,expires_at=None)
   else:grant_body['expires_at']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
   g=c.post('/api/agent-port/grants',headers=H,json=grant_body);assert g.status_code==201,g.text
   if mode=='finite-naive':
    async def make_naive():
     async with database.async_session() as db:
      row=await db.get(AgentGrant,g.json()['id']);row.expires_at=(datetime.now()+timedelta(hours=1));await db.commit()
    arun(make_naive)
   made=c.post('/agent/v1/proposals',headers={'Authorization':'Bearer '+g.json()['token']},json={'idempotency_key':'approve-'+mode,'expected_project_revision':1,'target_node_id':p['root_node_id'],'title':mode,'operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':'QA-ALPHA-TEST'}]});assert made.status_code==201,made.text
   url=f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve"
   first=c.post(url,headers=H,json={});assert first.status_code==200,first.text
   repeat=c.post(url,headers=H,json={});assert repeat.status_code==200 and repeat.json()=={'proposal_id':made.json()['proposal_id'],'status':'approved'}
   copied=arun(lambda:snapshot(p['id'],first.json()['receipt']['results'][0]['id']))
   assert copied[0].revision==2 and len(copied[1])==3 and len(copied[2])==3 and len(copied[3])==2 and len(copied[4])==1


def test_proposal_approval_rejects_invalid_grant_states_stably():
 with TestClient(app) as c:
  for state in ('finite-null','expired','revoked','inactive'):
   p=c.post('/api/projects',json={'name':'reject-'+state}).json();g=grant(c,p['id'],'propose')
   made=c.post('/agent/v1/proposals',headers={'Authorization':'Bearer '+g['token']},json={'idempotency_key':'reject-'+state,'expected_project_revision':1,'target_node_id':p['root_node_id'],'title':state,'operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':state}]});assert made.status_code==201,made.text
   async def poison():
    async with database.async_session() as db:
     row=await db.get(AgentGrant,g['id'])
     if state=='finite-null':row.expires_at=None
     elif state=='expired':row.expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
     elif state=='revoked':row.revoked_at=datetime.now(timezone.utc)
     else:row.status='inactive'
     await db.commit()
   arun(poison)
   response=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=H,json={})
   assert response.status_code==409,response.text;assert response.json()['detail']['code']=='GRANT_INACTIVE'
   project,nodes,blocks,edges,branches=arun(lambda:snapshot(p['id']));assert project.revision==1 and not branches
   async def status():
    async with database.async_session() as db:return (await db.get(AgentProposal,made.json()['proposal_id'])).status
   assert arun(status)=='pending'


def test_proposal_branch_copy_receipt_and_forced_failure_are_atomic(monkeypatch):
 with TestClient(app,raise_server_exceptions=False) as c:
  p=c.post('/api/projects',json={'name':'proposal'}).json();arun(lambda:seed(p['id'],p['root_node_id'],'proposal'));g=grant(c,p['id'],'propose')
  def propose(key,name):return c.post('/agent/v1/proposals',headers={'Authorization':'Bearer '+g['token']},json={'idempotency_key':key,'expected_project_revision':p['revision'],'target_node_id':p['root_node_id'],'title':name,'operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':name}]})
  made=propose('proposal-good','good');assert made.status_code==201,made.text
  approved=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=H,json={});assert approved.status_code==200,approved.text
  good_bid=approved.json()['receipt']['results'][0]['id'];copied=arun(lambda:snapshot(p['id'],good_bid));assert len(copied[1:4])==3 and [len(x) for x in copied[1:4]]==[3,3,2]
  async def good_state():
   async with database.async_session() as db:return await db.get(AgentProposal,made.json()['proposal_id']),await db.scalar(select(func.count()).select_from(AgentReceipt).where(AgentReceipt.project_id==p['id']))
  proposal,receipts=arun(good_state);assert proposal.status=='approved' and receipts==2  # proposal-store + approval

  # New project preserves expected rev=1 and isolates exact rollback counts.
  p2=c.post('/api/projects',json={'name':'failure'}).json();arun(lambda:seed(p2['id'],p2['root_node_id'],'failure'));g2=grant(c,p2['id'],'propose')
  made=c.post('/agent/v1/proposals',headers={'Authorization':'Bearer '+g2['token']},json={'idempotency_key':'proposal-bad','expected_project_revision':1,'target_node_id':p2['root_node_id'],'title':'bad','operations':[{'op':'create_branch','source_node_id':p2['root_node_id'],'expected_source_revision':1,'name':'bad'}]});assert made.status_code==201,made.text
  from sqlalchemy.ext.asyncio import AsyncSession
  original_flush=AsyncSession.flush
  injected=False
  async def fail_after_tree_staged(session,*args,**kwargs):
   nonlocal injected
   # The final flush sees both the copied tree and approval receipt staged, and
   # accurately exercises rollback of the complete transaction.
   if not injected and any(isinstance(row,AgentReceipt) for row in session.new):
    injected=True
    raise IntegrityError('forced canonical failure',{},RuntimeError('redacted'))
   return await original_flush(session,*args,**kwargs)
  monkeypatch.setattr(AsyncSession,'flush',fail_after_tree_staged)
  failed=c.post(f"/api/agent-port/proposals/{made.json()['proposal_id']}/approve",headers=H,json={});assert failed.status_code==409,failed.text
  async def failed_state():
   async with database.async_session() as db:
    project=await db.get(Project,p2['id']);proposal=await db.get(AgentProposal,made.json()['proposal_id']);branches=await db.scalar(select(func.count()).select_from(Branch).where(Branch.project_id==p2['id']));receipts=await db.scalar(select(func.count()).select_from(AgentReceipt).where(AgentReceipt.project_id==p2['id'],AgentReceipt.action_type=='batch'));logs=await db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.project_id==p2['id'],ActionLog.action_type=='agent_batch_applied'));nodes=await db.scalar(select(func.count()).select_from(Node).where(Node.project_id==p2['id'],Node.branch_id.is_not(None)));return project.revision,proposal.status,branches,receipts,logs,nodes
  assert arun(failed_state)==(1,'pending',0,0,0,0)

def test_independent_create_branch_races_have_one_atomic_tree_and_no_loser_artifacts():
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 with TestClient(app) as c:
  # GUI versus Agent, different ownership paths, same Project CAS.
  p=c.post('/api/projects',json={'name':'gui-agent-race'}).json();arun(lambda:seed(p['id'],p['root_node_id'],'race'));g=grant(c,p['id']);barrier=Barrier(2)
  def gui():barrier.wait();return c.post(f"/api/projects/{p['id']}/branches",json={'expected_project_revision':1,'source_node_id':p['root_node_id'],'name':'gui-race'})
  def agent():barrier.wait();return c.post('/agent/v1/batch',headers={'Authorization':'Bearer '+g['token']},json={'expected_project_revision':1,'idempotency_key':'gui-agent-loser','operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':'agent-race'}]})
  with ThreadPoolExecutor(max_workers=2) as pool:a=pool.submit(agent);b=pool.submit(gui);responses=[a.result(),b.result()]
  agent_response,gui_response=responses
  assert agent_response.status_code in (200,409) and gui_response.status_code in (201,409),[(r.status_code,r.text) for r in responses]
  assert sum(r.status_code==409 for r in responses)==1,[(r.status_code,r.text) for r in responses]
  async def race_state(pid):
   async with database.async_session() as db:
    project=await db.get(Project,pid);branches=(await db.execute(select(Branch).where(Branch.project_id==pid))).scalars().all();bids={b.id for b in branches};nodes=(await db.execute(select(Node).where(Node.branch_id.in_(bids)))).scalars().all() if bids else [];receipts=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==pid,AgentReceipt.action_type=='batch'))).scalars().all();logs=(await db.execute(select(ActionLog).where(ActionLog.project_id==pid,ActionLog.action_type.in_(['create_branch','agent_batch_applied'])))).scalars().all();source=await db.get(Node,p['root_node_id']);return project.revision,branches,nodes,receipts,logs,source.revision
  rev,branches,nodes,receipts,logs,source_rev=arun(lambda:race_state(p['id']));assert rev==2 and len(branches)==1 and len(nodes)==3 and source_rev==1 and len(logs)==1
  assert len(receipts)==(1 if agent_response.status_code==200 else 0)

  # Agent versus Agent, different keys: only the Project-CAS winner persists.
  p=c.post('/api/projects',json={'name':'agent-race'}).json();arun(lambda:seed(p['id'],p['root_node_id'],'arace'));g=grant(c,p['id']);barrier=Barrier(2)
  def writer(i):barrier.wait();return c.post('/agent/v1/batch',headers={'Authorization':'Bearer '+g['token']},json={'expected_project_revision':1,'idempotency_key':f'different-{i}','operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':f'agent-{i}'}]})
  with ThreadPoolExecutor(max_workers=2) as pool:responses=[pool.submit(writer,i) for i in range(2)];responses=[x.result() for x in responses]
  assert sorted(r.status_code for r in responses)==[200,409],[(r.status_code,r.text) for r in responses]
  rev,branches,nodes,receipts,logs,source_rev=arun(lambda:race_state(p['id']));assert (rev,len(branches),len(nodes),len(receipts),len(logs),source_rev)==(2,1,3,1,1,1)

def test_same_key_concurrent_branch_replay_has_one_receipt_and_tree():
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 with TestClient(app) as c:
  p=c.post('/api/projects',json={'name':'same-key'}).json();arun(lambda:seed(p['id'],p['root_node_id'],'same'));g=grant(c,p['id']);h={'Authorization':'Bearer '+g['token']};barrier=Barrier(2);body={'expected_project_revision':1,'idempotency_key':'same-key-race','operations':[{'op':'create_branch','source_node_id':p['root_node_id'],'expected_source_revision':1,'name':'same'}]}
  def writer():barrier.wait();return c.post('/agent/v1/batch',headers=h,json=body)
  with ThreadPoolExecutor(max_workers=2) as pool:a=pool.submit(writer);b=pool.submit(writer);responses=[a.result(),b.result()]
  assert [r.status_code for r in responses]==[200,200] and responses[0].json()==responses[1].json()
  async def counts():
   async with database.async_session() as db:
    project=await db.get(Project,p['id']);branches=(await db.execute(select(Branch).where(Branch.project_id==p['id']))).scalars().all();nodes=await db.scalar(select(func.count()).select_from(Node).where(Node.branch_id==branches[0].id));blocks=await db.scalar(select(func.count()).select_from(ContentBlock).join(Node,ContentBlock.node_id==Node.id).where(Node.branch_id==branches[0].id));edges=await db.scalar(select(func.count()).select_from(Edge).where(Edge.project_id==p['id'],Edge.from_node_id.in_(select(Node.id).where(Node.branch_id==branches[0].id))));receipts=await db.scalar(select(func.count()).select_from(AgentReceipt).where(AgentReceipt.project_id==p['id'],AgentReceipt.action_type=='batch'));logs=await db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.project_id==p['id'],ActionLog.action_type=='agent_batch_applied'));source=await db.get(Node,p['root_node_id']);return project.revision,len(branches),nodes,blocks,edges,receipts,logs,source.revision
  assert arun(counts)==(2,1,3,3,2,1,1,1)
