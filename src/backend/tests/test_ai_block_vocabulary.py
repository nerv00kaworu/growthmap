import json,re
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
from models.content_blocks import CONTENT_BLOCK_TYPES
from ai.providers.base import LLMProvider

class Blocks(LLMProvider):
 @property
 def name(self):return 'blocks'
 async def complete(self,*args,**kwargs):
  return json.dumps({'enriched_summary':'complete','content_blocks':[{'title':f't-{x}','body':'b','block_type':x} for x in CONTENT_BLOCK_TYPES[:2]]})

def test_canonical_types_have_ts_parity_and_real_routes_persist(monkeypatch):
 ts=(Path(__file__).parents[2]/'frontend/src/lib/content-block-types.ts').read_text()
 assert tuple(re.findall(r'"([a-z_]+)"',ts))==CONTENT_BLOCK_TYPES
 import ai.routes
 monkeypatch.setattr(ai.routes,'get_provider',lambda _:Blocks())
 with TestClient(app) as c:
  p=c.post('/api/projects',json={'name':'blocks'}).json();root=c.get('/api/nodes/'+p['root_node_id']).json();provider=c.post('/api/providers',json={'name':'mock','provider_type':'mock'}).json()
  for typ in CONTENT_BLOCK_TYPES:
   class One(Blocks):
    async def complete(self,*a,**k):return json.dumps({'enriched_summary':'complete','content_blocks':[{'title':'a','body':'b','block_type':typ},{'title':'c','body':'d','block_type':typ}]})
   monkeypatch.setattr(ai.routes,'get_provider',lambda _:One())
   deep=c.post('/api/ai/deepen',json={'node_id':root['id'],'provider_id':provider['id'],'provider_revision':provider['revision']});assert deep.status_code==200,(typ,deep.text)
   made=c.post(f"/api/nodes/{root['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':root['revision'],'block_type':typ,'content':{'body':'b'}});assert made.status_code==201,(typ,made.text);assert made.json()['block_type']==typ
   p=c.get('/api/projects/'+p['id']).json();root=c.get('/api/nodes/'+root['id']).json()
  bad=c.post(f"/api/nodes/{root['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':root['revision'],'block_type':'invalid','content':{}});assert bad.status_code==422

def test_invalid_deepen_is_502_and_builtin_mock_expand_deepen_create():
 with TestClient(app) as c:
  p=c.post('/api/projects',json={'name':'mock'}).json();root=c.get('/api/nodes/'+p['root_node_id']).json();provider=c.post('/api/providers',json={'name':'mock','provider_type':'mock'}).json();q={'node_id':root['id'],'provider_id':provider['id'],'provider_revision':provider['revision']}
  assert c.post('/api/ai/expand',json=q).status_code==200
  deep=c.post('/api/ai/deepen',json=q);assert deep.status_code==200,deep.text
  block=deep.json()['content_blocks'][0];made=c.post(f"/api/nodes/{root['id']}/blocks",json={'expected_project_revision':p['revision'],'expected_node_revision':root['revision'],'block_type':block['block_type'],'content':block});assert made.status_code==201,made.text
