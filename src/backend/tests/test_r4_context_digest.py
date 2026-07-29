import os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient

class ContextDigest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(); os.environ['DATABASE_URL']=f"sqlite+aiosqlite:///{cls.tmp.name}/db";os.environ['APP_ENV']='test';os.environ['GROWTHMAP_HUMAN_CONTROL_TOKEN']='h';sys.path.insert(0,str(Path(__file__).parents[1]));import main;cls.c=TestClient(main.app);cls.c.__enter__();cls.hh={'Authorization':'Bearer h'}
 @classmethod
 def tearDownClass(cls):cls.c.__exit__(None,None,None);cls.tmp.cleanup()
 def setUp(self):
  p=self.c.post('/api/projects',json={'name':'digest','description':'d','goal':'g'}).json();self.p=p;self.root=self.c.get('/api/nodes/'+p['root_node_id']).json();grant=self.c.post('/api/agent-port/grants',headers=self.hh,json={'project_id':p['id'],'permission':'write','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'d','agent_identity':'d'}).json();self.h={'Authorization':'Bearer '+grant['token']}
 def context(self,objective='ship'):return self.c.get(f"/agent/v1/context/{self.root['id']}?objective={objective}",headers=self.h).json()
 def test_complete_packet_digest_changes_for_objective_project_edge_block_branch(self):
  first=self.context(); self.assertEqual(first['project']['goal'],'g'); self.assertNotEqual(first['snapshot_digest'],self.context('other')['snapshot_digest'])
  p=self.c.patch(f"/api/projects/{self.p['id']}",json={'expected_project_revision':self.p['revision'],'description':'changed'}).json(); self.assertNotEqual(first['snapshot_digest'],self.context()['snapshot_digest']); first=self.context()
  r=self.c.get('/api/nodes/'+self.root['id']).json(); child=self.c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':r['revision'],'title':'c','parent_id':r['id']}).json(); self.assertNotEqual(first['snapshot_digest'],self.context()['snapshot_digest']);first=self.context()
  p=self.c.get('/api/projects/'+p['id']).json();r=self.c.get('/api/nodes/'+r['id']).json(); self.c.post(f"/api/nodes/{r['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':r['revision'],'content':{'body':'x'}});self.assertNotEqual(first['snapshot_digest'],self.context()['snapshot_digest'])
  # Branch metadata is represented on scope-visible nodes; creating a branch changes project revision/context.
  first=self.context();p=self.c.get('/api/projects/'+p['id']).json();r=self.c.get('/api/nodes/'+r['id']).json();self.c.post(f"/api/projects/{p['id']}/branches",json={'expected_project_revision':p['revision'],'source_node_id':r['id'],'name':'b'});self.assertNotEqual(first['snapshot_digest'],self.context()['snapshot_digest'])
