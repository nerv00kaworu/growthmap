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
  p=self.c.get('/api/projects/'+p['id']).json();r=self.c.get('/api/nodes/'+r['id']).json(); block=self.c.post(f"/api/nodes/{r['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':r['revision'],'block_type':'code','content':{'body':'x'},'order_index':7}).json();packet=self.context();self.assertNotEqual(first['snapshot_digest'],packet['snapshot_digest']);self.assertEqual(packet['content_blocks'][0]['id'],block['id']);self.assertEqual(packet['content_blocks'][0]['source']['created_by'],'human');self.assertEqual(packet['target']['file_paths'],[]);self.assertIn('rules_text',packet['target'])
  # Branch metadata is represented on scope-visible nodes; creating a branch changes project revision/context.
  first=self.context();p=self.c.get('/api/projects/'+p['id']).json();r=self.c.get('/api/nodes/'+r['id']).json();self.c.post(f"/api/projects/{p['id']}/branches",json={'expected_project_revision':p['revision'],'source_node_id':r['id'],'name':'b'});self.assertNotEqual(first['snapshot_digest'],self.context()['snapshot_digest'])
 def test_exact_node_scope_excludes_outside_nodes_blocks_and_sources(self):
  p=self.c.get('/api/projects/'+self.p['id']).json();root=self.c.get('/api/nodes/'+self.root['id']).json();child=self.c.post(f"/api/projects/{p['id']}/nodes",json={'expected_project_revision':p['revision'],'expected_parent_revision':root['revision'],'title':'secret child','parent_id':root['id']}).json();p=self.c.get('/api/projects/'+self.p['id']).json();child=self.c.get('/api/nodes/'+child['id']).json();self.c.post(f"/api/nodes/{child['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':child['revision'],'content':{'body':'OUTSIDE SECRET'}})
  grant=self.c.post('/api/agent-port/grants',headers=self.hh,json={'project_id':self.p['id'],'permission':'read','node_scope_id':self.root['id'],'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'label':'scoped','agent_identity':'scoped'}).json();packet=self.c.get(f"/agent/v1/context/{self.root['id']}",headers={'Authorization':'Bearer '+grant['token']}).json();wire=str(packet);self.assertNotIn(child['id'],wire);self.assertNotIn('OUTSIDE SECRET',wire);self.assertEqual(packet['content_blocks'],[])
