"""Focused shared delete_edge acceptance contract (subprocess-isolated)."""
import os, subprocess, sys
if os.environ.get("GROWTHMAP_DELETE_EDGE_CHILD") == "1":
    import asyncio,os,tempfile
    from datetime import datetime,timedelta,timezone
    os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/delete-edge.db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='human'
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from main import app
    from db.database import async_session
    from models.models import ActionLog,Edge,Node
    H={'Authorization':'Bearer human'}
    def grant(c,p,**scope):
     x=c.post('/api/agent-port/grants',headers=H,json={'project_id':p,'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'d','agent_identity':'agent',**scope}).json();return {'Authorization':'Bearer '+x['token']}
    def mk(c,name,relation='supports'):
     p=c.post('/api/projects',json={'name':name}).json();r=p['root_node_id'];rr=c.get('/api/nodes/'+r).json();n=c.post('/api/projects/'+p['id']+'/nodes',json={'expected_project_revision':p['revision'],'expected_parent_revision':rr['revision'],'parent_id':r,'title':'n'}).json();rr=c.get('/api/nodes/'+r).json();n=c.get('/api/nodes/'+n['id']).json();pr=c.get('/api/projects/'+p['id']).json()['revision'];e=c.post('/api/edges',json={'expected_project_revision':pr,'expected_from_revision':rr['revision'],'expected_to_revision':n['revision'],'from_node_id':r,'to_node_id':n['id'],'relation_type':relation}).json();return p['id'],r,n['id'],e
    def batch(c,h,p,key,ops,rev):return c.post('/agent/v1/batch',headers=h,json={'expected_project_revision':rev,'idempotency_key':key,'operations':ops})
    async def logs(p):
     async with async_session() as db:return (await db.execute(select(ActionLog).where(ActionLog.project_id==p,ActionLog.action_type=='graph_relation_deleted'))).scalars().all()

    def test_gui_agent_parity_history_endpoint_no_touch_and_replay():
     with TestClient(app) as c:
      for mode in ('gui','agent'):
       p,a,b,e=mk(c,mode);pr=c.get('/api/projects/'+p).json()['revision'];before={x:c.get('/api/nodes/'+x).json()['revision'] for x in (a,b)}
       if mode=='gui':out=c.request('DELETE','/api/edges/'+e['id'],json={'expected_project_revision':pr,'expected_revision':e['revision']})
       else:
        h=grant(c,p);op={'op':'delete_edge','edge_id':e['id'],'expected_revision':e['revision']};out=batch(c,h,p,'delete-edge', [op],pr);assert out.json()['results']==[{'op':'delete_edge','id':e['id']}];assert batch(c,h,p,'delete-edge',[op],pr).json()==out.json()
       assert out.status_code in (200,204),out.text;assert c.get('/api/projects/'+p).json()['revision']==pr+1;assert e['id'] not in {row['id'] for row in c.get('/api/projects/'+p+'/edges').json()};assert {x:c.get('/api/nodes/'+x).json()['revision'] for x in (a,b)}==before
       history=asyncio.run(logs(p));assert len(history)==1 and set(history[0].payload)<= {'edge_id','from_node_id','to_node_id','relation_type','provenance'} and 'note' not in str(history[0].payload).lower()

    def test_strict_scope_child_stale_and_prewrite_conflicts():
     with TestClient(app) as c:
      p,a,b,e=mk(c,'bounds');pr=c.get('/api/projects/'+p).json()['revision'];h=grant(c,p,node_scope_id=a);op={'op':'delete_edge','edge_id':e['id'],'expected_revision':1}
      assert batch(c,h,p,'scope-denied',[op],pr).status_code==403
      h=grant(c,p);assert batch(c,h,p,'extra',[{**op,'note':'secret'}],pr).status_code==422;assert batch(c,h,p,'stale-edge',[{**op,'expected_revision':2}],pr).status_code==409
      for reverse,code in ((False,'NEW_EDGE_DELETE_UNSUPPORTED'),(True,'NEW_EDGE_DELETE_UNSUPPORTED')):
       new='11111111-1111-4111-8111-11111111111'+str(int(reverse));create={'op':'create_edge','id':new,'from_node_id':a,'to_node_id':b,'expected_from_revision':c.get('/api/nodes/'+a).json()['revision'],'expected_to_revision':c.get('/api/nodes/'+b).json()['revision'],'relation_type':'references'};delete={'op':'delete_edge','edge_id':new,'expected_revision':1};r=batch(c,h,p,'new-del-'+str(reverse),[delete,create] if reverse else [create,delete],pr);assert r.status_code==422 and r.json()['detail']['code']==code and c.get('/api/projects/'+p).json()['revision']==pr
      for ops,code,key in (([op,op],'DUPLICATE_EDGE_DELETE','duplicate'),([{'op':'update_edge','edge_id':e['id'],'expected_revision':1,'fields':{'note':'x'}},op],'EDGE_DELETE_CONFLICT','mixed-key')):
       for reverse in (False,True):r=batch(c,h,p,key+str(reverse),list(reversed(ops)) if reverse else ops,pr);assert r.status_code==422 and r.json()['detail']['code']==code and c.get('/api/projects/'+p).json()['revision']==pr
      pc,_,_,_=mk(c,'child');ec=next(x for x in c.get('/api/projects/'+pc+'/edges').json() if x['relation_type']=='child_of');rev=c.get('/api/projects/'+pc).json()['revision'];assert c.request('DELETE','/api/edges/'+ec['id'],json={'expected_project_revision':rev,'expected_revision':ec['revision']}).status_code==400;assert batch(c,grant(c,pc),pc,'child-del',[{'op':'delete_edge','edge_id':ec['id'],'expected_revision':ec['revision']}],rev).status_code==422
else:
    def test_delete_edge_shared_acceptance_isolated():
        env={**os.environ,"GROWTHMAP_DELETE_EDGE_CHILD":"1","PYTHONPATH":os.path.dirname(os.path.dirname(__file__)),"APP_ENV":"test","GROWTHMAP_HUMAN_CONTROL_TOKEN":"human"}
        for key in ("GROWTHMAP_DESKTOP_MODE","GROWTHMAP_SESSION_TOKEN","GROWTHMAP_FRESH_INSTALL"):
            env.pop(key,None)
        result=subprocess.run([sys.executable,"-m","pytest","-q",__file__],env=env,text=True,capture_output=True)
        assert result.returncode==0,result.stdout+result.stderr
