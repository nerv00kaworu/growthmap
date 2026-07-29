import os,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from fastapi.testclient import TestClient

class AgentPortV1(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();os.environ["DATABASE_URL"]=f"sqlite+aiosqlite:///{cls.tmp.name}/db.sqlite";os.environ["APP_ENV"]="test";os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"]="human-test";sys.path.insert(0,str(Path(__file__).parents[1]));import main;cls.human={"Authorization":"Bearer human-test"};cls.client=TestClient(main.app);cls.client.__enter__()
 @classmethod
 def tearDownClass(cls):cls.client.__exit__(None,None,None);cls.tmp.cleanup()
 def setUp(self):
  p=self.client.post("/api/projects",json={"name":"Agent dogfood"}).json();self.pid=p["id"];self.root=p["root_node_id"]
 def grant(self,permission="write",scope=None,expired=False):
  body={"project_id":self.pid,"permission":permission,"expires_at":(datetime.now(timezone.utc)+(-timedelta(minutes=2) if expired else timedelta(hours=1))).isoformat(),"label":"test","agent_identity":"neutral-test"};body.update(scope or {});return self.client.post("/api/agent-port/grants",json=body,headers=self.human)
 def auth(self,t):return {"Authorization":"Bearer "+t}
 def revisions(self):
  return self.client.get(f"/api/projects/{self.pid}").json(),self.client.get(f"/api/nodes/{self.root}").json()
 def human_patch(self,**fields):
  p,n=self.revisions();return self.client.patch(f"/api/nodes/{self.root}",json={"expected_project_revision":p["revision"],"expected_revision":n["revision"],**fields})
 def child(self,title="other"):
  p,_=self.revisions();return self.client.post(f"/api/projects/{self.pid}/nodes",json={"expected_project_revision":p["revision"],"title":title,"parent_id":self.root})
 def test_security_proposal_revision_scope_revoke_idempotency_and_context(self):
  read=self.grant("read").json();r=self.client.post("/agent/v1/batch",headers=self.auth(read["token"]),json={"expected_project_revision":1,"idempotency_key":"read-denied","operations":[{"op":"update_node","node_id":self.root,"expected_revision":1,"fields":{"title":"x"}}]});self.assertEqual(r.status_code,403)
  prop=self.grant("propose").json();before=self.client.get(f"/api/nodes/{self.root}").json()["title"];r=self.client.post("/agent/v1/proposals",headers=self.auth(prop["token"]),json={"idempotency_key":"proposal-001","expected_project_revision":1,"target_node_id":self.root,"title":"review","operations":[{"op":"update_node","node_id":self.root,"expected_revision":1,"fields":{"title":"proposed"}}]});self.assertEqual(r.status_code,201,r.text);self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["title"],before);approved=self.client.post(f'/api/agent-port/proposals/{r.json()["proposal_id"]}/approve',json={},headers=self.human);self.assertEqual(approved.status_code,200,approved.text);self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["title"],"proposed")
  write=self.grant().json();proj=self.client.get("/agent/v1/project",headers=self.auth(write["token"])).json();node=self.client.get(f"/api/nodes/{self.root}").json();body={"expected_project_revision":proj["revision"],"idempotency_key":"batch-0001","operations":[{"op":"update_node","node_id":self.root,"expected_revision":node["revision"],"fields":{"summary":"agent"}}]};a=self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=body);self.assertEqual(a.status_code,200,a.text);b=self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=body);self.assertEqual(a.json(),b.json());bad={**body,"operations":[{**body["operations"][0],"fields":{"summary":"other"}}]};self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=bad).status_code,409)
  old=proj["revision"];self.assertEqual(self.human_patch(summary="human").status_code,200);stale={"expected_project_revision":old,"idempotency_key":"stale-0001","operations":[{"op":"update_node","node_id":self.root,"expected_revision":node["revision"],"fields":{"summary":"stale"}}]};self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=stale).status_code,409)
  child=self.child().json();scoped=self.grant("write",{"node_scope_id":self.root}).json();cur=self.client.get("/agent/v1/project",headers=self.auth(scoped["token"])).json();self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(scoped["token"]),json={"expected_project_revision":cur["revision"],"idempotency_key":"scope-001","operations":[{"op":"update_node","node_id":child["id"],"expected_revision":child["revision"],"fields":{"title":"no"}}]}).status_code,403)
  c1=self.client.get(f"/agent/v1/context/{self.root}",headers=self.auth(write["token"])).json();self.human_patch(description="human changed");c2=self.client.get(f"/agent/v1/context/{self.root}",headers=self.auth(write["token"])).json();self.assertNotEqual(c1["snapshot_digest"],c2["snapshot_digest"])
  self.client.post(f'/api/agent-port/grants/{write["id"]}/revoke',headers=self.human);self.assertEqual(self.client.get("/agent/v1/project",headers=self.auth(write["token"])).status_code,401);self.assertEqual(self.grant(expired=True).status_code,422)
 def test_readback_timeline_and_token_query_forbidden(self):
  g=self.grant("propose").json();h=self.auth(g["token"]);r=self.client.post("/agent/v1/readbacks",headers=h,json={"idempotency_key":"readback-1","target_node_id":self.root,"summary":"implemented","commit_refs":["abc"],"files":["a.py"],"tests":[{"name":"unit","status":"passed"}]});self.assertEqual(r.status_code,201,r.text);activity=self.client.get(f"/api/agent-port/activity?project_id={self.pid}",headers=self.human).json();self.assertEqual(activity["readbacks"][0]["summary"],"implemented");self.assertEqual(self.client.get(f"/agent/v1/project?token={g['token']}",headers=h).status_code,400)
 def test_two_writers_same_revision_exactly_one(self):
  a=self.grant().json();b=self.grant().json();p=self.client.get("/agent/v1/project",headers=self.auth(a["token"])).json();n=self.client.get(f"/api/nodes/{self.root}").json();statuses=[]
  for i,g in enumerate((a,b)):statuses.append(self.client.post("/agent/v1/batch",headers=self.auth(g["token"]),json={"expected_project_revision":p["revision"],"idempotency_key":f"writer-{i}","operations":[{"op":"update_node","node_id":self.root,"expected_revision":n["revision"],"fields":{"summary":str(i)}}]}).status_code)
  self.assertEqual(sorted(statuses),[200,409])
