import os, subprocess, sys

def test_desktop_secret_routes_require_existing_nonmock_provider(tmp_path):
    script=r'''
from fastapi.testclient import TestClient
from main import app
from desktop.secrets import get
h={'Authorization':'Bearer '+'test-session-token'}
with TestClient(app) as c:
 missing='deleted-provider-id'
 assert c.put(f'/api/desktop/secrets/{missing}',headers=h,json={'api_key':'***'}).status_code==404
 assert get(missing) is None
 assert c.delete(f'/api/desktop/secrets/{missing}',headers=h).status_code==404
 assert get(missing) is None
 p=c.post('/api/providers',headers=h,json={'name':'fixture','provider_type':'openai_compatible','endpoint':'http://fixture.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_FIXTURE','model_name':'fixture','capabilities':[],'cost_level':'none','enabled':True}).json()
 r=c.put(f"/api/desktop/secrets/{p['id']}",headers=h,json={'api_key':'***'}); assert r.status_code==204, r.text
 assert get(p['id']) is not None
 assert c.delete(f"/api/desktop/secrets/{p['id']}",headers=h).status_code==204
 assert get(p['id']) is None
 mock=c.post('/api/providers',headers=h,json={'name':'mock','provider_type':'mock','endpoint':'','secret_env_key':'GROWTHMAP_LLM_KEY_MOCK','model_name':'mock','capabilities':[],'cost_level':'none','enabled':True}).json()
 assert c.put(f"/api/desktop/secrets/{mock['id']}",headers=h,json={'api_key':'***'}).status_code==400
 assert get(mock['id']) is None
'''
    env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','DATABASE_URL':f"sqlite+aiosqlite:///{tmp_path/'provider.db'}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json')}
    result=subprocess.run([sys.executable,'-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
