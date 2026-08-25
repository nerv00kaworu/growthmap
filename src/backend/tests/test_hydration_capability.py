import os,subprocess,sys,textwrap
from pathlib import Path
ROOT=Path(__file__).parents[1]
def run(script,cap='A'*43):
 env={**os.environ,'PYTHONPATH':str(ROOT),'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_SESSION_TOKEN':'test-session-token','GROWTHMAP_HYDRATION_CAPABILITY':cap,'GROWTHMAP_FRESH_INSTALL':'1','DATABASE_URL':'sqlite+aiosqlite:////tmp/gm-hydration-capability.db','GROWTHMAP_TRIAL_STATE_FILE':'/tmp/gm-hydration-trial.json','GROWTHMAP_STARTUP_VERDICT_MODE':'fresh','GROWTHMAP_STARTUP_VERDICT_NONCE':'NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN','GROWTHMAP_STARTUP_VERDICT_MAC':'54e8b06bfded81a38763b02f2056c887ea2ed62225ab51a807a663ade5d79ab8'}
 for f in ('/tmp/gm-hydration-capability.db','/tmp/gm-hydration-trial.json'):
  try: os.unlink(f)
  except FileNotFoundError: pass
 return subprocess.run([sys.executable,'-c',textwrap.dedent(script)],cwd=ROOT,env=env,text=True,capture_output=True)
def test_read_only_sidecar_without_capability_rejects_hydrate_and_seal():
 r=run('''
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as c:
 h={'Authorization':'Bearer test-session-token','X-GrowthMap-Hydration-Capability':'A'*43}
 assert c.post('/api/desktop/secrets/hydration/seal',headers=h).status_code==403
 assert c.put('/api/desktop/secrets/00000000-0000-4000-8000-000000000000/hydrate',headers=h,json={'api_key':'***'}).status_code==403
''',cap='')
 assert r.returncode==0,r.stderr

def test_private_capability_missing_wrong_sealed_and_old_sidecar_rejected():
 r=run('''
from fastapi.testclient import TestClient
from main import app
from desktop import secrets
with TestClient(app) as c:
 h={'Authorization':'Bearer test-session-token'}
 from datetime import datetime,timezone
 c.post('/api/desktop/trial/start',headers={**h,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 resp=c.post('/api/providers',headers=h,json={'name':'p','provider_type':'openai_compatible','endpoint':'https://example.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_X','model_name':'m','capabilities':[],'cost_level':'none','enabled':True});assert resp.status_code<300,resp.text;p=resp.json();url=f"/api/desktop/secrets/{p['id']}/hydrate"
 assert c.put(url,headers=h,json={'api_key':'x'}).status_code==403
 assert c.put(url,headers={**h,'X-GrowthMap-Hydration-Capability':'B'*43},json={'api_key':'x'}).status_code==403
 good={**h,'X-GrowthMap-Hydration-Capability':'A'*43}
 assert c.put(url,headers=good,json={'api_key':'x'}).status_code==204
 sealed=c.post('/api/desktop/secrets/hydration/seal',headers=good);assert sealed.status_code==204;assert sealed.content==b''
 assert c.put(url,headers=good,json={'api_key':'y'}).status_code==403
 assert secrets.get(p['id'])=='x'
''');assert r.returncode==0,r.stderr
 r=run('''
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as c:
 base={'Authorization':'Bearer test-session-token'}
 from datetime import datetime,timezone
 c.post('/api/desktop/trial/start',headers={**base,'X-GrowthMap-Fresh-Install':'1'},json={'started_at':datetime.now(timezone.utc).isoformat(),'installation_id':'test-installation'})
 h={**base,'X-GrowthMap-Hydration-Capability':'A'*43}
 p=c.post('/api/providers',headers={'Authorization':'Bearer test-session-token'},json={'name':'p','provider_type':'openai_compatible','endpoint':'https://example.invalid','secret_env_key':'GROWTHMAP_LLM_KEY_X','model_name':'m','capabilities':[],'cost_level':'none','enabled':True}).json()
 assert c.put(f"/api/desktop/secrets/{p['id']}/hydrate",headers=h,json={'api_key':'x'}).status_code==403
''',cap='C'*43);assert r.returncode==0,r.stderr
