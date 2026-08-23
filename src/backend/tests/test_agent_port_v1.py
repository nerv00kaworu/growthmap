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

 def test_branch_graph_rejects_cross_project_cross_branch_and_malformed_root(self):
  from sqlalchemy import update
  from db.database import async_session
  from models.models import AgentGrant,Edge
  def branch():
   p,n=self.revisions()
   made=self.client.post(f"/api/projects/{self.pid}/branches",json={"expected_project_revision":p["revision"],"source_node_id":self.root,"name":"scope"})
   self.assertEqual(made.status_code,201,made.text)
   row=made.json();tree=self.client.get(f"/api/branches/{row['id']}/subtree").json()["tree"]
   return row,tree
  for case in ("cross-project","cross-branch","malformed-root"):
   scoped_branch,scope_root=branch()
   made=self.grant("read",{"branch_root_id":scope_root["id"]}).json()
   other=self.client.post("/api/projects",json={"name":f"foreign-{case}"}).json()
   if case=="cross-project": target=other["root_node_id"]
   elif case=="cross-branch":
    second,second_root=branch();target=second_root["id"]
   else: target=None
   async def corrupt():
    async with async_session() as db:
     if target:
      db.add(Edge(project_id=self.pid,from_node_id=scope_root["id"],to_node_id=target,relation_type="child_of"))
     else:
      await db.execute(update(AgentGrant).where(AgentGrant.id==made["id"]).values(branch_root_id=other["root_node_id"]))
     await db.commit()
   asyncio.run(corrupt())
   graph=self.client.get("/agent/v1/graph",headers=self.auth(made["token"]))
   self.assertEqual(graph.status_code,409,(case,graph.text))
   self.assertNotIn(other["id"],graph.text)
 def test_explicit_node_and_branch_scopes_validate_complete_graph_and_branch_ownership(self):
  from sqlalchemy import update
  from db.database import async_session
  from models.models import Edge,Node
  def make_node(title,parent=None,branch_id=None):
   p=self.client.get(f"/api/projects/{self.pid}").json()
   parent=parent or self.root;n=self.client.get(f"/api/nodes/{parent}").json()
   body={"title":title,"parent_id":parent,"expected_project_revision":p["revision"],"expected_parent_revision":n["revision"]}
   if branch_id:body["branch_id"]=branch_id
   made=self.client.post(f"/api/projects/{self.pid}/nodes",json=body);self.assertEqual(made.status_code,201,made.text);return made.json()
  def make_branch(name):
   p,n=self.revisions();made=self.client.post(f"/api/projects/{self.pid}/branches",json={"expected_project_revision":p["revision"],"source_node_id":self.root,"name":name});self.assertEqual(made.status_code,201,made.text)
   row=made.json();return row,self.client.get(f"/api/branches/{row['id']}/subtree").json()["tree"]
  async def edges(rows):
   async with async_session() as db:
    for source,target,project in rows:db.add(Edge(project_id=project,from_node_id=source,to_node_id=target,relation_type="child_of"))
    await db.commit()
  def rejected(root,case):
   grant=self.grant("read",{"node_scope_id":root}).json();response=self.client.get("/agent/v1/graph",headers=self.auth(grant["token"]));self.assertEqual(response.status_code,409,(case,response.text))

  # Build all canonical branch fixtures before inserting hostile graph rows.
  branch,branch_root=make_branch("other-scope")
  valid_branch,valid_branch_root=make_branch("valid-branch");valid_child=make_node("valid-branch-child",valid_branch_root["id"],valid_branch["id"])
  foreign=self.client.post("/api/projects",json={"name":"foreign-node-scope"}).json()
  foreign_branch=self.client.post(f"/api/projects/{foreign['id']}/branches",json={"expected_project_revision":foreign["revision"],"source_node_id":foreign["root_node_id"],"name":"foreign-owner"}).json()

  # Valid explicit node grant remains singleton even though its closure is validated.
  valid=make_node("valid-node");valid_grant=self.grant("read",{"node_scope_id":valid["id"]}).json()
  graph=self.client.get("/agent/v1/graph",headers=self.auth(valid_grant["token"]));self.assertEqual(graph.status_code,200,graph.text);self.assertEqual({n["id"] for n in graph.json()["nodes"]},{valid["id"]})

  self_cycle=make_node("self-cycle");asyncio.run(edges([(self_cycle["id"],self_cycle["id"],self.pid)]));rejected(self_cycle["id"],"self-cycle")
  parallel=make_node("parallel");parallel_child=make_node("parallel-child",parallel["id"]);asyncio.run(edges([(parallel["id"],parallel_child["id"],self.pid)]));rejected(parallel["id"],"parallel")
  diamond=make_node("diamond");left=make_node("left",diamond["id"]);right=make_node("right",diamond["id"]);shared=make_node("shared",left["id"]);asyncio.run(edges([(right["id"],shared["id"],self.pid)]));rejected(diamond["id"],"repeated")
  external=make_node("external-root");external_child=make_node("external-child",external["id"]);outside=make_node("outside-parent");asyncio.run(edges([(outside["id"],external_child["id"],self.pid)]));rejected(external["id"],"external second parent")
  deep=make_node("different-depth");deep_left=make_node("deep-left",deep["id"]);deep_right=make_node("deep-right",deep["id"]);deep_shared=make_node("deep-shared",deep_left["id"]);deep_mid=make_node("deep-mid",deep_right["id"]);asyncio.run(edges([(deep_mid["id"],deep_shared["id"],self.pid)]));rejected(deep["id"],"different-depth repeated")
  cross_project=make_node("cross-project");asyncio.run(edges([(cross_project["id"],foreign["root_node_id"],self.pid)]));rejected(cross_project["id"],"cross-project")
  cross_branch=make_node("cross-branch");asyncio.run(edges([(cross_branch["id"],branch_root["id"],self.pid)]));rejected(cross_branch["id"],"cross-branch")

  # Valid explicit branch grant still returns its complete same-branch tree.
  branch_grant=self.grant("read",{"branch_root_id":valid_branch_root["id"]}).json();graph=self.client.get("/agent/v1/graph",headers=self.auth(branch_grant["token"]));self.assertEqual(graph.status_code,200,graph.text);self.assertTrue({valid_branch_root["id"],valid_child["id"]}.issubset({n["id"] for n in graph.json()["nodes"]}))
  # An authenticated branch scope fails closed when a same-branch node outside
  # its closure becomes a second parent of an inside descendant.
  branch_outside=make_node("branch-outside")
  async def move_outside_into_branch():
   async with async_session() as db:
    await db.execute(update(Node).where(Node.id==branch_outside["id"]).values(branch_id=valid_branch["id"]));await db.commit()
  asyncio.run(move_outside_into_branch());asyncio.run(edges([(branch_outside["id"],valid_child["id"],self.pid)]))
  graph=self.client.get("/agent/v1/graph",headers=self.auth(branch_grant["token"]));self.assertEqual(graph.status_code,409,graph.text);self.assertNotIn(branch_outside["id"],graph.text)

  # FK-valid foreign Branch ownership must fail for either explicit root kind.
  for field in ("node_scope_id","branch_root_id"):
   victim=make_node(f"foreign-owner-{field}")
   async def corrupt():
    async with async_session() as db:
     await db.execute(update(Node).where(Node.id==victim["id"]).values(branch_id=foreign_branch["id"]));await db.commit()
   asyncio.run(corrupt());grant=self.grant("read",{field:victim["id"]}).json();response=self.client.get("/agent/v1/graph",headers=self.auth(grant["token"]));self.assertEqual(response.status_code,409,(field,response.text));self.assertNotIn(foreign_branch["id"],response.text)
 def test_unscoped_project_and_workspace_graphs_project_exact_main_nodes(self):
  p,n=self.revisions()
  main_child=self.child("main-visible").json()
  p,n=self.revisions();made=self.client.post(f"/api/projects/{self.pid}/branches",json={"expected_project_revision":p["revision"],"source_node_id":self.root,"name":"hidden-branch"});self.assertEqual(made.status_code,201,made.text)
  branch=made.json();branch_root=self.client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
  p=self.client.get(f"/api/projects/{self.pid}").json();bn=self.client.get(f"/api/nodes/{branch_root['id']}").json();branch_child=self.client.post(f"/api/projects/{self.pid}/nodes",json={"expected_project_revision":p["revision"],"expected_parent_revision":bn["revision"],"title":"branch-hidden","parent_id":branch_root["id"],"branch_id":branch["id"]}).json()
  expected={self.root,main_child["id"]};hidden={branch_root["id"],branch_child["id"]}
  project_grant=self.grant("read").json();response=self.client.get("/agent/v1/graph",headers=self.auth(project_grant["token"]));self.assertEqual(response.status_code,200,response.text);self.assertEqual({row["id"] for row in response.json()["nodes"]},expected);self.assertTrue(hidden.isdisjoint({row["id"] for row in response.json()["nodes"]}))

 def test_valid_node_scope_graph_returns_exact_allowed_nodes_edges_and_blocks_only(self):
  from db.database import async_session
  from models.models import ContentBlock
  allowed=self.child("allowed-node").json();unrelated=self.child("unrelated-main").json()
  p,n=self.revisions();made=self.client.post(f"/api/projects/{self.pid}/branches",json={"expected_project_revision":p["revision"],"source_node_id":self.root,"name":"excluded-branch"});self.assertEqual(made.status_code,201,made.text)
  branch=made.json();branch_root=self.client.get(f"/api/branches/{branch['id']}/subtree").json()["tree"]
  foreign=self.client.post("/api/projects",json={"name":"foreign-projection"}).json()
  async def seed_blocks():
   async with async_session() as db:
    db.add_all([
     ContentBlock(node_id=allowed["id"],block_type="note",content={"marker":"allowed"},order_index=0),
     ContentBlock(node_id=unrelated["id"],block_type="note",content={"marker":"unrelated"},order_index=0),
     ContentBlock(node_id=branch_root["id"],block_type="note",content={"marker":"branch"},order_index=0),
     ContentBlock(node_id=foreign["root_node_id"],block_type="note",content={"marker":"foreign"},order_index=0),
    ]);await db.commit()
  asyncio.run(seed_blocks())
  grant=self.grant("read",{"node_scope_id":allowed["id"]}).json();response=self.client.get("/agent/v1/graph",headers=self.auth(grant["token"]));self.assertEqual(response.status_code,200,response.text);body=response.json()
  self.assertEqual({row["id"] for row in body["nodes"]},{allowed["id"]})
  self.assertEqual(body["edges"],[])
  self.assertEqual(len(body["content_blocks"]),1);self.assertEqual(body["content_blocks"][0]["node_id"],allowed["id"]);self.assertEqual(body["content_blocks"][0]["content"],{"marker":"allowed"})
  omitted={self.root,unrelated["id"],branch_root["id"],foreign["root_node_id"]};self.assertTrue(omitted.isdisjoint({row["id"] for row in body["nodes"]}));self.assertTrue(omitted.isdisjoint({row["node_id"] for row in body["content_blocks"]}))
