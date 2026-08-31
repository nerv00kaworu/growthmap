import os, subprocess, sys

def test_desktop_secret_routes_require_existing_nonmock_provider(tmp_path):
    script=r'''
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
from desktop.secrets import get
h={'Authorization':'Bearer '+'test-session-token'}
with TestClient(app) as c:
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 missing='deleted-provider-id'
 assert c.put(f'/api/desktop/secrets/{missing}',headers=h,json={'api_key':'***','operation_id':'a'*48,'expected_revision':1}).status_code==404
 assert get(missing) is None
 assert c.request('DELETE',f'/api/desktop/secrets/{missing}',headers=h,json={'operation_id':'a'*48,'expected_revision':1}).status_code==404
 assert get(missing) is None
 p=c.post('/api/providers',headers=h,json={'name':'fixture','provider_type':'openai_compatible','endpoint':'http://fixture.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_FIXTURE','model_name':'fixture','capabilities':[],'cost_level':'none','enabled':True}).json()
 assert c.put(f"/api/desktop/secrets/{p['id']}",headers=h,json={'api_key':'***'}).status_code==422
 assert c.put(f"/api/desktop/secrets/{p['id']}",headers=h,json={'api_key':'***','operation_id':'a'*48,'expected_revision':p['revision']+1}).status_code==409
 assert get(p['id']) is None
 r=c.put(f"/api/desktop/secrets/{p['id']}",headers=h,json={'api_key':'***','operation_id':'a'*48,'expected_revision':p['revision']}); assert r.status_code==204, r.text
 assert get(p['id']) is not None
 assert c.request('DELETE',f"/api/desktop/secrets/{p['id']}",headers=h,json={'operation_id':'a'*48,'expected_revision':p['revision']+1}).status_code==204
 assert get(p['id']) is None
 mock=c.post('/api/providers',headers=h,json={'name':'mock','provider_type':'mock','endpoint':'','secret_env_key':'GROWTHMAP_LLM_KEY_MOCK','model_name':'mock','capabilities':[],'cost_level':'none','enabled':True}).json()
 assert c.put(f"/api/desktop/secrets/{mock['id']}",headers=h,json={'api_key':'***','operation_id':'a'*48,'expected_revision':mock['revision']}).status_code==400
 assert get(mock['id']) is None
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'provider.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(tmp_path/'trial.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
