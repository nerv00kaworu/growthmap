import os, subprocess, sys

def test_desktop_api_secret_memory_only_lifecycle(tmp_path):
    script=r'''
import ai.routes
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
from ai.providers.base import LLMProvider
class CapturingProvider(LLMProvider):
 @property
 def name(self): return 'fixture'
 async def complete(self,system,user,model=None,temperature=.7,max_tokens=2000):
  assert self.api_key=='memory-key'
  if 'project context' in user.lower() or '專案上下文' in user:
   return '[{"title":"fixture child","summary":"fixture summary","node_type":"idea"}]'
  return 'OK'
def fake_provider(config):
 p=CapturingProvider();p.api_key=config.api_key;return p
ai.routes.get_provider=fake_provider
import ai.providers.registry
ai.providers.registry.get_provider=fake_provider
h={'Authorization':'Bearer test-session-token'}
with TestClient(app) as c:
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 project=c.post('/api/projects',headers=h,json={'name':'secret-test'}).json()
 provider=c.post('/api/providers',headers=h,json={'name':'fixture','provider_type':'openai_compatible','endpoint':'http://fixture.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_FIXTURE','model_name':'fixture','capabilities':[],'cost_level':'none','enabled':True}).json()
 pid=provider['id']
 # Inherited env-only key is deliberately ignored in desktop mode.
 missing=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid})
 assert missing.status_code==400 and 'desktop secure storage' in missing.text
 assert c.put(f'/api/desktop/secrets/{pid}',headers=h,json={'api_key':'memory-key'}).status_code==204
 tested=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid})
 assert tested.status_code==200 and tested.json()['ok'] is True, tested.text
 expanded=c.post('/api/ai/expand',headers=h,json={'node_id':project['root_node_id'],'provider_id':pid,'count':1})
 # Resolver/provider consumed the memory key without making a network request.
 assert expanded.status_code==200 and expanded.json()['suggestions'][0]['title']=='fixture child', expanded.text
 assert c.delete(f'/api/desktop/secrets/{pid}',headers=h).status_code==204
 removed=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid})
 assert removed.status_code==400 and 'desktop secure storage' in removed.text
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8','GROWTHMAP_LLM_KEY_FIXTURE':'env-must-be-ignored','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'secret.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
