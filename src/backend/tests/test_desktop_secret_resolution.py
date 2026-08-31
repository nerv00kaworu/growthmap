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
  try: payload=__import__('json').loads(user)
  except (TypeError,ValueError): payload=None
  if isinstance(payload,dict) and set(payload)=={'context','mode_key','mode','requested_count','existing_children','existing_siblings','instruction'}:
   assert isinstance(payload['context'],dict)
   assert payload['mode_key']=='explore' and isinstance(payload['mode'],str)
   assert isinstance(payload['requested_count'],int) and not isinstance(payload['requested_count'],bool)
   for key in ('existing_children','existing_siblings'):
    assert set(payload[key])=={'label','titles'}
    assert isinstance(payload[key]['label'],str)
    assert isinstance(payload[key]['titles'],list) and all(isinstance(x,str) for x in payload[key]['titles'])
   assert set(payload['instruction'])=={'label','value'}
   assert isinstance(payload['instruction']['label'],str)
   assert payload['instruction']['value'] is None or isinstance(payload['instruction']['value'],str)
   return '[{"title":"fixture child","summary":"fixture summary","node_type":"idea"}]'
  return 'OK'
def fake_provider(config):
 p=CapturingProvider();p.api_key=config.api_key;return p
ai.routes.get_provider=fake_provider
import ai.providers.registry
ai.providers.registry.get_provider=fake_provider
h={'Authorization':'Bearer test-session-token'}
with TestClient(app,raise_server_exceptions=False) as c:
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 project=c.post('/api/projects',headers=h,json={'name':'secret-test'}).json()
 provider=c.post('/api/providers',headers=h,json={'name':'fixture','provider_type':'openai_compatible','endpoint':'http://fixture.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_FIXTURE','model_name':'fixture','capabilities':[],'cost_level':'none','enabled':True}).json()
 pid=provider['id']
 assert provider['credential_status']=='unavailable'
 selection_revision=provider['selection_revision']
 assert c.put('/api/providers/selection',headers=h,json={'provider_id':pid,'expected_selection_revision':selection_revision}).status_code==409
 # Inherited env-only key is deliberately ignored in desktop mode.
 missing=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid,'provider_revision':provider['revision'],'selection_revision':selection_revision})
 assert missing.status_code==409 and 'LLM_SELECTION_CHANGED' in missing.text,missing.text
 before=provider['revision']
 saved=c.put(f'/api/desktop/secrets/{pid}',headers=h,json={'api_key':'memory-key','operation_id':'a'*48,'expected_revision':before})
 assert saved.status_code==204,saved.text
 provider=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert provider['revision']==before+1,(before,provider['revision'])
 assert provider['credential_status']=='ready' and provider['secret_change_operation_id']=='a'*48
 selected=c.put('/api/providers/selection',headers=h,json={'provider_id':pid,'expected_selection_revision':provider['selection_revision']})
 assert selected.status_code==200,selected.text
 selection_revision=selected.json()['selection_revision']
 tested=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid,'provider_revision':provider['revision'],'selection_revision':selection_revision})
 assert tested.status_code==200 and tested.json()['ok'] is True, tested.text
 expanded=c.post('/api/ai/expand',headers=h,json={'node_id':project['root_node_id'],'provider_id':pid,'provider_revision':provider['revision'],'selection_revision':selection_revision,'count':1})
 # Resolver/provider consumed the memory key without making a network request.
 assert expanded.status_code==200 and expanded.json()['suggestions'][0]['title']=='fixture child', expanded.text
 # A sidecar restart loses process memory. Projection becomes unavailable until
 # the desktop hydrates through the revision-neutral startup endpoint.
 import desktop.secrets as memory
 memory.delete(pid)
 unavailable=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert unavailable['credential_status']=='unavailable'
 assert unavailable['revision']==provider['revision']
 hydrated=c.put(f'/api/desktop/secrets/{pid}/hydrate',headers={**h,'X-GrowthMap-Hydration-Capability':'H'*43},json={'api_key':'memory-key'})
 assert hydrated.status_code==204,hydrated.text
 rehydrated=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert rehydrated['credential_status']=='ready' and rehydrated['revision']==provider['revision']
 before=provider['revision']
 deleted=c.request('DELETE',f'/api/desktop/secrets/{pid}',headers=h,json={'operation_id':'b'*48,'expected_revision':before})
 assert deleted.status_code==204,deleted.text
 provider=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert provider['revision']==before+1 and provider['secret_change_operation_id']=='b'*48,(before,provider['revision'])
 removed=c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid,'provider_revision':provider['revision'],'selection_revision':selection_revision})
 assert removed.status_code==400 and 'LLM_CONFIGURATION_ERROR' in removed.text
 # A failed store exposes only safe pending state and is explicitly recoverable
 import desktop.routes as dr
 original=dr.put
 def fail(*_): raise RuntimeError('store failure')
 dr.put=fail
 failed=c.put(f'/api/desktop/secrets/{pid}',headers=h,json={'api_key':'***','operation_id':'c'*48,'expected_revision':provider['revision']})
 assert failed.status_code==500 and 'memory-key' not in failed.text
 pending=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert pending['secret_change_pending'] is True and pending['credential_status']=='recovery_required'
 assert c.post('/api/ai/test-connection',headers=h,json={'provider_id':pid,'provider_revision':pending['revision'],'selection_revision':selection_revision}).status_code==409
 stale=c.post(f'/api/desktop/secrets/{pid}/recover',headers=h,json={'revision':pending['revision']-1,'operation':'set','operation_id':'a'*48,'api_key':'***'})
 assert stale.status_code==409
 mismatch=c.post(f'/api/desktop/secrets/{pid}/recover',headers=h,json={'revision':pending['revision'],'operation':'set','operation_id':'b'*48,'api_key':'***'})
 assert mismatch.status_code==409
 dr.put=original
 recovered=c.post(f'/api/desktop/secrets/{pid}/recover',headers=h,json={'revision':pending['revision'],'operation':'set','operation_id':'c'*48,'api_key':'***'})
 assert recovered.status_code==204,recovered.text
 ready=next(x for x in c.get('/api/providers',headers=h).json() if x['id']==pid)
 assert ready['revision']==pending['revision'] and ready['secret_change_pending'] is False
 assert ready['credential_status']=='ready'
 # Hydration cannot bypass the transition latch.
 dr.put=fail
 failed=c.put(f'/api/desktop/secrets/{pid}',headers=h,json={'api_key':'***','operation_id':'d'*48,'expected_revision':ready['revision']})
 assert failed.status_code==500
 blocked=c.put(f'/api/desktop/secrets/{pid}/hydrate',headers={**h,'X-GrowthMap-Hydration-Capability':'H'*43},json={'api_key':'***'})
 assert blocked.status_code==409 and 'PROVIDER_CREDENTIAL_RECOVERY_REQUIRED' in blocked.text
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_HYDRATION_CAPABILITY':'H'*43,'GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8','GROWTHMAP_LLM_KEY_FIXTURE':'env-must-be-ignored','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'secret.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
