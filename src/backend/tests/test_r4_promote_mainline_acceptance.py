"""Dedicated file-backed shared promote_mainline acceptance contract."""
import os,subprocess,sys
from pathlib import Path
BACKEND=Path(__file__).parents[1]
RUNNER=r'''
import asyncio,os,tempfile,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from threading import Barrier
os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/promote.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human'
from fastapi.testclient import TestClient
from sqlalchemy import select
from main import app
from db.database import async_session
from models.models import ActionLog,AgentProposal,AgentReceipt,Edge,Node,Project
import api.routes as gui_routes,agent_port.service as service
H={'Authorization':'Bearer human'}
def arun(x):return asyncio.run(x)
def grant(c,p,permission='write',**scope):
 r=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':permission,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'p','agent_identity':'agent',**scope});assert r.status_code==201,r.text;return {'Authorization':'Bearer '+r.json()['token']}
def mk(c,name,count=2):
 p=c.post('/api/projects',json={'name':name}).json();root=p['root_node_id'];children=[]
 for i in range(count):
  pr=c.get('/api/projects/'+p['id']).json();rr=c.get('/api/nodes/'+root).json();children.append(c.post('/api/projects/'+p['id']+'/nodes',json={'expected_project_revision':pr['revision'],'expected_parent_revision':rr['revision'],'parent_id':root,'title':str(i)}).json()['id'])
 edges=c.get('/api/projects/'+p['id']+'/edges?relation_type=child_of').json();return p['id'],root,children,edges
def mainline(edges):return next((e for e in edges if e['is_mainline']),None)
def target(edges):return next((e for e in edges if not e['is_mainline']),edges[0])
def op(e,sibs):return {'op':'promote_mainline','edge_id':e['id'],'expected_revision':e['revision'],'expected_sibling_revisions':{s['id']:s['revision'] for s in sibs if s['is_mainline'] and s['id']!=e['id']}}
def batch(c,h,p,key,ops,rev):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
def gui(c,route,p,e,edges):
 body={'expected_project_revision':c.get('/api/projects/'+p).json()['revision'],'expected_revision':e['revision'],'expected_sibling_revisions':op(e,edges)['expected_sibling_revisions']}
 url='/api/edges/'+e['id']+'/promote-mainline' if route=='edge' else '/api/nodes/'+e['from_node_id']+'/promote-child/'+e['to_node_id'];return c.post(url,json=body)
async def state(p,pid=None):
 async with async_session() as db:
  pr=await db.get(Project,p);es=(await db.execute(select(Edge).where(Edge.project_id==p).order_by(Edge.id))).scalars().all();ns=(await db.execute(select(Node).where(Node.project_id==p).order_by(Node.id))).scalars().all();ls=(await db.execute(select(ActionLog).where(ActionLog.project_id==p,ActionLog.action_type=='mainline_promoted'))).scalars().all();q=await db.get(AgentProposal,pid) if pid else None;rs=(await db.execute(select(AgentReceipt).where(AgentReceipt.project_id==p))).scalars().all();return pr,es,ns,ls,q,rs
def frozen(p):
 pr,es,ns,ls,q,rs=arun(state(p));return pr.revision,[(e.id,e.revision,e.is_mainline) for e in es],[(n.id,n.revision) for n in ns],[(l.id,l.payload) for l in ls],[(r.id,r.idempotency_key) for r in rs]
with TestClient(app,raise_server_exceptions=True) as c:
 # Both GUI routes, direct Agent, and approved proposal share snapshots/history; 0/1/multi sibling and already-mainline.
 for mode,count in [('edge',2),('child',2),('agent',2),('proposal',3),('zero',1)]:
  p,root,kids,edges=mk(c,mode,count);e=target(edges);before=frozen(p);pid=None
  if mode in ('edge','child','zero'):r=gui(c,'edge' if mode!='child' else 'child',p,e,edges)
  elif mode=='agent':r=batch(c,grant(c,p),p,'promote-agent',[op(e,edges)],before[0])
  else:
   made=c.post('/agent/v1/proposals',headers=grant(c,p,'propose'),json={'expected_project_revision':before[0],'idempotency_key':'promote-proposal','title':'p','operations':[op(e,edges)]});assert made.status_code==201;pid=made.json()['proposal_id'];assert frozen(p)[:4]==before[:4];r=c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'ok'})
  assert r.status_code==200,r.text;pr,es,ns,logs,q,rs=arun(state(p,pid));assert pr.revision==before[0]+1 and sum(x.is_mainline for x in es)==1 and next(x for x in es if x.id==e['id']).revision==e['revision']+1 and [(n.id,n.revision) for n in ns]==before[2] and len(logs)==1
  payload=logs[0].payload;assert set(payload)<= {'edge_id','parent_node_id','child_node_id','demoted_edge_ids','provenance'} and set(payload['demoted_edge_ids'])==set(op(e,edges)['expected_sibling_revisions'])
  # already-mainline target also bumps target/project and has exact empty sibling map
  current=[{'id':x.id,'from_node_id':x.from_node_id,'to_node_id':x.to_node_id,'revision':x.revision,'is_mainline':x.is_mainline} for x in es];t=next(x for x in current if x['is_mainline']);rev=pr.revision;r=gui(c,'edge',p,t,current);assert r.status_code==200;pr2,es2,ns2,logs2,_,_=arun(state(p));assert pr2.revision==rev+1 and next(x for x in es2 if x.id==t['id']).revision==t['revision']+1 and len(logs2)==2
 # Exact sibling union missing/extra/stale, target stale: exact no-write.
 for kind in ('missing','extra','staleSibling','staleTarget'):
  p,root,kids,edges=mk(c,kind,3);e=target(edges);body=op(e,edges);rev=c.get('/api/projects/'+p).json()['revision'];before=frozen(p)
  if kind=='missing':body['expected_sibling_revisions']={}
  elif kind=='extra':body['expected_sibling_revisions'][str(uuid.uuid4())]=1
  elif kind=='staleSibling':body['expected_sibling_revisions'][next(iter(body['expected_sibling_revisions']))]+=1
  else:body['expected_revision']+=1
  r=batch(c,grant(c,p),p,'bad-'+kind,[body],rev);assert r.status_code==409 and frozen(p)==before
 # Scope must include target and demoted sibling endpoints.
 p,root,kids,edges=mk(c,'scope',2);e=target(edges);rev=c.get('/api/projects/'+p).json()['revision'];before=frozen(p);denied=batch(c,grant(c,p,node_scope_id=e['to_node_id']),p,'scope-key',[op(e,edges)],rev);assert denied.status_code==403,(denied.status_code,denied.text);assert frozen(p)==before
 # Stable prewrite collisions: duplicate, same-parent multi, update/delete/create versus promote, both orders.
 p,root,kids,edges=mk(c,'collisions',3);a=target(edges);b=next(e for e in edges if e['id']!=a['id']);h=grant(c,p);rev=c.get('/api/projects/'+p).json()['revision']
 cases=[([op(a,edges),op(a,edges)],'EDGE_PROMOTE_CONFLICT'),([op(a,edges),op(b,edges)],'MULTIPLE_PARENT_PROMOTIONS'),([op(a,edges),{'op':'update_edge','edge_id':a['id'],'expected_revision':a['revision'],'fields':{'note':'x'}}],'EDGE_PROMOTE_CONFLICT'),([op(a,edges),{'op':'delete_edge','edge_id':a['id'],'expected_revision':a['revision']}],'EDGE_PROMOTE_CONFLICT')]
 for i,(ops,code) in enumerate(cases):
  for reverse in (False,True):before=frozen(p);r=batch(c,h,p,f'collision-{i}-{reverse}',list(reversed(ops)) if reverse else ops,rev);assert r.status_code==422 and r.json()['detail']['code']==code and frozen(p)==before
 new=str(uuid.uuid4());create={'op':'create_edge','id':new,'from_node_id':a['from_node_id'],'to_node_id':a['to_node_id'],'expected_from_revision':c.get('/api/nodes/'+a['from_node_id']).json()['revision'],'expected_to_revision':c.get('/api/nodes/'+a['to_node_id']).json()['revision'],'relation_type':'child_of'};prom={'op':'promote_mainline','edge_id':new,'expected_revision':1,'expected_sibling_revisions':{}}
 for reverse in (False,True):before=frozen(p);r=batch(c,h,p,'create-promote-'+str(reverse),[prom,create] if reverse else [create,prom],rev);assert r.status_code==422 and r.json()['detail']['code']=='NEW_EDGE_PROMOTE_UNSUPPORTED' and frozen(p)==before
 # Direct idempotency and mismatch.
 p,root,kids,edges=mk(c,'idem',2);e=target(edges);rev=c.get('/api/projects/'+p).json()['revision'];h=grant(c,p);r=batch(c,h,p,'idem-key',[op(e,edges)],rev);assert r.status_code==200;assert batch(c,h,p,'idem-key',[op(e,edges)],rev).json()==r.json();bad={**op(e,edges),'expected_revision':e['revision']+1};assert batch(c,h,p,'idem-key',[bad],rev).status_code==409
 # Proposal stale/fault remains pending and writes no approval receipt.
 p,root,kids,edges=mk(c,'proposal-stale',2);e=target(edges);rev=c.get('/api/projects/'+p).json()['revision'];made=c.post('/agent/v1/proposals',headers=grant(c,p,'propose'),json={'expected_project_revision':rev,'idempotency_key':'stale-key','title':'p','operations':[op(e,edges)]});pid=made.json()['proposal_id'];gui(c,'edge',p,e,edges);before=frozen(p);assert c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'x'}).status_code==409;assert frozen(p)==before;assert arun(state(p,pid))[4].status=='pending' and not [x for x in arun(state(p,pid))[5] if x.idempotency_key=='proposal:'+pid]
 # Late post-history rollback for both GUI routes, direct, proposal.
 for mode in ('edge','child','direct','proposal'):
  p,root,kids,edges=mk(c,'fault-'+mode,2);e=target(edges);rev=c.get('/api/projects/'+p).json()['revision'];module=gui_routes if mode in ('edge','child') else service;original=module.apply_promote_mainline;pid=None
  if mode=='proposal':made=c.post('/agent/v1/proposals',headers=grant(c,p,'propose'),json={'expected_project_revision':rev,'idempotency_key':'fault-key','title':'p','operations':[op(e,edges)]});pid=made.json()['proposal_id']
  before=frozen(p)
  async def fault(*args,**kwargs):out=await original(*args,**kwargs);await args[0].flush();raise RuntimeError('late')
  module.apply_promote_mainline=fault
  try:
   try:
    if mode in ('edge','child'):gui(c,mode,p,e,edges)
    elif mode=='direct':batch(c,grant(c,p),p,'fault-direct',[op(e,edges)],rev)
    else:c.post('/api/agent-port/proposals/'+pid+'/approve',headers=H,json={'review_note':'x'})
   except RuntimeError:pass
  finally:module.apply_promote_mainline=original
  assert frozen(p)==before
  if pid:assert arun(state(p,pid))[4].status=='pending'
 # GUI/Agent same file-backed project CAS races, three rounds, exactly one write.
 for i in range(3):
  p,root,kids,edges=mk(c,'race'+str(i),2);e=target(edges);rev=c.get('/api/projects/'+p).json()['revision'];h=grant(c,p);bar=Barrier(2)
  def g():bar.wait();return gui(c,'edge',p,e,edges)
  def a():bar.wait();return batch(c,h,p,'race-key-'+str(i),[op(e,edges)],rev)
  with ThreadPoolExecutor(max_workers=2) as pool:r1,r2=pool.submit(g),pool.submit(a);answers=[r1.result(),r2.result()]
  assert sorted(x.status_code for x in answers)==[200,409],[(x.status_code,x.text) for x in answers];pr,es,ns,logs,q,rs=arun(state(p));assert pr.revision==rev+1 and len(logs)==1 and sum(x.is_mainline for x in es)==1
'''
def test_promote_mainline_shared_acceptance_isolated():
 env={**os.environ,'PYTHONPATH':str(BACKEND)};r=subprocess.run([sys.executable,'-c',RUNNER],cwd=BACKEND,env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
