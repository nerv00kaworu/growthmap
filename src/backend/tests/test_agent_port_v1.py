import asyncio,os,subprocess,sys,tempfile,unittest,uuid
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
  p,n=self.revisions();return self.client.post(f"/api/projects/{self.pid}/nodes",json={"expected_project_revision":p["revision"],"expected_parent_revision":n["revision"],"title":title,"parent_id":self.root})
 def test_non_desktop_human_routes_require_explicit_capability_and_bearer(self):
  script='''import os,sys,tempfile\nfrom fastapi.testclient import TestClient\nt=tempfile.TemporaryDirectory();os.environ["DATABASE_URL"]=f"sqlite+aiosqlite:///{t.name}/db";os.environ["APP_ENV"]="test"\nif sys.argv[1]:os.environ["GROWTHMAP_HUMAN_CONTROL_TOKEN"]=sys.argv[1]\nsys.path.insert(0,sys.argv[2]);import main\nwith TestClient(main.app) as c:\n print(c.get("/api/agent-port/grants?project_id=00000000-0000-0000-0000-000000000000").status_code,c.get("/api/agent-port/grants?project_id=00000000-0000-0000-0000-000000000000",headers={"Authorization":"Bearer wrong"}).status_code,c.get("/api/agent-port/grants?project_id=00000000-0000-0000-0000-000000000000",headers={"Authorization":"Bearer "+sys.argv[1]}).status_code if sys.argv[1] else "-")\n'''
  backend=str(Path(__file__).parents[1]);env={k:v for k,v in os.environ.items() if k not in {"GROWTHMAP_HUMAN_CONTROL_TOKEN","GROWTHMAP_SESSION_TOKEN","GROWTHMAP_DESKTOP_MODE"}}
  disabled=subprocess.run([sys.executable,"-c",script,"",backend],env=env,text=True,capture_output=True,check=True);self.assertEqual(disabled.stdout.strip(),"403 403 -")
  enabled=subprocess.run([sys.executable,"-c",script,"explicit-local",backend],env=env,text=True,capture_output=True,check=True);self.assertEqual(enabled.stdout.strip(),"401 401 200")
 def test_security_proposal_revision_scope_revoke_idempotency_and_context(self):
  read=self.grant("read").json();r=self.client.post("/agent/v1/batch",headers=self.auth(read["token"]),json={"expected_project_revision":1,"idempotency_key":"read-denied","operations":[{"op":"update_node","node_id":self.root,"expected_revision":1,"fields":{"title":"x"}}]});self.assertEqual(r.status_code,403)
  prop=self.grant("propose").json();before=self.client.get(f"/api/nodes/{self.root}").json()["title"];r=self.client.post("/agent/v1/proposals",headers=self.auth(prop["token"]),json={"idempotency_key":"proposal-001","expected_project_revision":1,"target_node_id":self.root,"title":"review","operations":[{"op":"update_node","node_id":self.root,"expected_revision":1,"fields":{"title":"proposed"}}]});self.assertEqual(r.status_code,201,r.text);self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["title"],before);approved=self.client.post(f'/api/agent-port/proposals/{r.json()["proposal_id"]}/approve',json={},headers=self.human);self.assertEqual(approved.status_code,200,approved.text);self.assertEqual(self.client.get(f"/api/nodes/{self.root}").json()["title"],"proposed")
  write=self.grant().json();proj=self.client.get("/agent/v1/project",headers=self.auth(write["token"])).json();node=self.client.get(f"/api/nodes/{self.root}").json();body={"expected_project_revision":proj["revision"],"idempotency_key":"batch-0001","operations":[{"op":"update_node","node_id":self.root,"expected_revision":node["revision"],"fields":{"summary":"agent"}}]};a=self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=body);self.assertEqual(a.status_code,200,a.text);b=self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=body);self.assertEqual(a.json(),b.json());bad={**body,"operations":[{**body["operations"][0],"fields":{"summary":"other"}}]};self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=bad).status_code,409)
  old=proj["revision"];self.assertEqual(self.human_patch(summary="human").status_code,200);stale={"expected_project_revision":old,"idempotency_key":"stale-0001","operations":[{"op":"update_node","node_id":self.root,"expected_revision":node["revision"],"fields":{"summary":"stale"}}]};self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(write["token"]),json=stale).status_code,409)
  child=self.child().json();scoped=self.grant("write",{"node_scope_id":self.root}).json();cur=self.client.get("/agent/v1/project",headers=self.auth(scoped["token"])).json();self.assertEqual(self.client.post("/agent/v1/batch",headers=self.auth(scoped["token"]),json={"expected_project_revision":cur["revision"],"idempotency_key":"scope-001","operations":[{"op":"update_node","node_id":child["id"],"expected_revision":child["revision"],"fields":{"title":"no"}}]}).status_code,403)
  c1=self.client.get(f"/agent/v1/context/{self.root}",headers=self.auth(write["token"])).json();self.human_patch(description="human changed");c2=self.client.get(f"/agent/v1/context/{self.root}",headers=self.auth(write["token"])).json();self.assertNotEqual(c1["snapshot_digest"],c2["snapshot_digest"])
  self.client.post(f'/api/agent-port/grants/{write["id"]}/revoke',headers=self.human);self.assertEqual(self.client.get("/agent/v1/project",headers=self.auth(write["token"])).status_code,401);self.assertEqual(self.grant(expired=True).status_code,422)
 def test_readback_timeline_filter_identity_and_token_query_forbidden(self):
  other=self.child("second target").json();g=self.grant("propose").json();h=self.auth(g["token"])
  revision=self.client.get(f"/api/projects/{self.pid}").json()["revision"]
  for key,target in (("root",self.root),("other",other["id"])):
   event=self.client.post("/agent/v1/events",headers=h,json={"idempotency_key":f"event-{key}","target_node_id":target,"event_type":"completed","message":f"{key} event"});self.assertEqual(event.status_code,201,event.text)
   proposal=self.client.post("/agent/v1/proposals",headers=h,json={"idempotency_key":f"proposal-{key}","expected_project_revision":revision,"target_node_id":target,"title":f"{key} proposal","operations":[{"op":"update_node","node_id":target,"expected_revision":other["revision"] if target==other["id"] else self.client.get(f"/api/nodes/{self.root}").json()["revision"],"fields":{"summary":key}}]});self.assertEqual(proposal.status_code,201,proposal.text)
  complete={"idempotency_key":"readback-root","target_node_id":self.root,"summary":"implemented","commit_refs":["abc"],"files":["a.py"],"tests":[{"name":"unit","status":"passed","detail":"focused"}],"decisions":["keep API bounded"],"risks":["none"],"todos":["review"],"evidence":[{"name":"diff","status":"verified","detail":"clean"}]}
  r=self.client.post("/agent/v1/readbacks",headers=h,json=complete);self.assertEqual(r.status_code,201,r.text)
  r=self.client.post("/agent/v1/readbacks",headers=h,json={"idempotency_key":"readback-other","target_node_id":other["id"],"summary":"other node"});self.assertEqual(r.status_code,201,r.text)
  filtered=self.client.get(f"/api/agent-port/activity?project_id={self.pid}&target_node_id={self.root}",headers=self.human);self.assertEqual(filtered.status_code,200,filtered.text);body=filtered.json();rows=body["readbacks"];self.assertEqual(len(rows),1);self.assertEqual(rows[0]["target_node_id"],self.root);self.assertEqual(rows[0]["agent"],"neutral-test");self.assertEqual(rows[0]["source"],"test");self.assertEqual(rows[0]["decisions"],["keep API bounded"]);self.assertEqual(rows[0]["evidence"][0]["name"],"diff");self.assertEqual([x["title"] for x in body["proposals"]],["root proposal"]);self.assertEqual([x["message"] for x in body["events"]],["root event"])
  activity=self.client.get(f"/api/agent-port/activity?project_id={self.pid}",headers=self.human).json();self.assertEqual({x["summary"] for x in activity["readbacks"]},{"implemented","other node"});self.assertEqual({x["title"] for x in activity["proposals"]},{"root proposal","other proposal"});self.assertEqual({x["message"] for x in activity["events"]},{"root event","other event"})
  self.assertEqual(self.client.get(f"/agent/v1/project?token={g['token']}",headers=h).status_code,400)
 def test_activity_outerjoin_returns_persisted_readback_with_missing_grant(self):
  from sqlalchemy import text
  from db.database import engine
  orphan_id=str(uuid.uuid4());missing_grant=str(uuid.uuid4())
  async def insert_orphan():
   # This isolated connection emulates an imported/legacy SQLite row. Restore
   # FK enforcement before returning it to the pool.
   async with engine.connect() as conn:
    await conn.execute(text("PRAGMA foreign_keys=OFF"))
    try:
     await conn.execute(text("INSERT INTO agent_readbacks (id,grant_id,project_id,target_node_id,commit_refs,files,tests,decisions,risks,todos,evidence,summary,created_at) VALUES (:id,:grant,:project,:target,'[]','[]','[]','[]','[]','[]','[]','orphan-safe',CURRENT_TIMESTAMP)"),{"id":orphan_id,"grant":missing_grant,"project":self.pid,"target":self.root})
     await conn.commit()
    finally:
     await conn.execute(text("PRAGMA foreign_keys=ON"))
  asyncio.run(insert_orphan())
  response=self.client.get(f"/api/agent-port/activity?project_id={self.pid}&target_node_id={self.root}",headers=self.human);self.assertEqual(response.status_code,200,response.text)
  row=next(x for x in response.json()["readbacks"] if x["id"]==orphan_id);self.assertEqual(row["summary"],"orphan-safe");self.assertNotIn("agent",row);self.assertNotIn("source",row)
 def test_activity_filter_rejects_invalid_and_cross_project_target_without_leak(self):
  other_project=self.client.post("/api/projects",json={"name":"other project"}).json()
  invalid=self.client.get(f"/api/agent-port/activity?project_id={self.pid}&target_node_id=not-a-uuid",headers=self.human);self.assertEqual(invalid.status_code,422)
  cross=self.client.get(f"/api/agent-port/activity?project_id={self.pid}&target_node_id={other_project['root_node_id']}",headers=self.human);self.assertEqual(cross.status_code,404);self.assertNotIn(other_project["id"],cross.text)
 def test_two_writers_same_revision_exactly_one(self):
  a=self.grant().json();b=self.grant().json();p=self.client.get("/agent/v1/project",headers=self.auth(a["token"])).json();n=self.client.get(f"/api/nodes/{self.root}").json();statuses=[]
  for i,g in enumerate((a,b)):statuses.append(self.client.post("/agent/v1/batch",headers=self.auth(g["token"]),json={"expected_project_revision":p["revision"],"idempotency_key":f"writer-{i}","operations":[{"op":"update_node","node_id":self.root,"expected_revision":n["revision"],"fields":{"summary":str(i)}}]}).status_code)
  self.assertEqual(sorted(statuses),[200,409])
