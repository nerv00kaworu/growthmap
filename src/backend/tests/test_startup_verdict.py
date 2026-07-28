import hashlib,hmac,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

BACKEND=Path(__file__).parents[1]
def signed_env(mode,token='verdict-test-token'):
 nonce='N'*43;mac=hmac.new(token.encode(),f'growthmap-startup-v1:{mode}:{nonce}'.encode(),hashlib.sha256).hexdigest()
 return {'GROWTHMAP_SESSION_TOKEN':token,'GROWTHMAP_STARTUP_VERDICT_MODE':mode,'GROWTHMAP_STARTUP_VERDICT_NONCE':nonce,'GROWTHMAP_STARTUP_VERDICT_MAC':mac}
def run(tmp_path,mode,trial_doc):
 tmp_path.mkdir(parents=True,exist_ok=True)
 import sqlite3
 db=tmp_path/'db.sqlite';c=sqlite3.connect(db);c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at DATETIME,updated_at DATETIME)');c.commit();c.close()
 if mode=='trial':
  env0={**os.environ,'DATABASE_URL':f'sqlite+aiosqlite:///{db}'};env0.pop('GROWTHMAP_DESKTOP_MODE',None);subprocess.run([sys.executable,'-c','from fastapi.testclient import TestClient;from main import app\nwith TestClient(app): pass'],cwd=BACKEND,env=env0,check=True,capture_output=True)
 trial=tmp_path/'trial.json';trial.write_text(json.dumps(trial_doc) if isinstance(trial_doc,dict) else trial_doc)
 code='''from fastapi.testclient import TestClient
from main import app
h={'Authorization':'Bearer verdict-test-token'}
with TestClient(app) as c:
 e=c.get('/api/desktop/entitlement',headers=h);assert e.status_code==200
 print(e.json()['state'])
 assert c.get('/api/projects',headers=h).status_code==200
 print(c.post('/api/projects',headers=h,json={'name':'blocked-or-allowed'}).status_code)
'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'0','GROWTHMAP_DB_QUERY_ONLY':'1' if mode=='extraction' else '0','GROWTHMAP_SCHEMA_CURRENT':'1' if mode=='trial' else '0','DATABASE_URL':f"sqlite+aiosqlite:///{db}",'GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(trial),**signed_env(mode)}
 return subprocess.run([sys.executable,'-c',code],cwd=BACKEND,env=env,text=True,capture_output=True)
def active():
 now=datetime.now(timezone.utc).isoformat();return {'schema_version':1,'installation_id':'matching-installation','started_at':now,'last_seen_at':now}
def test_electron_extraction_overrides_valid_trial_json_and_keeps_reads(tmp_path):
 result=run(tmp_path,'extraction',active());assert result.returncode==0,result.stderr;assert result.stdout.splitlines()==['extraction','403']
def test_corrupt_or_disagreed_secure_marker_verdict_stays_extraction(tmp_path):
 for i,state in enumerate((active(),'{bad')):
  result=run(tmp_path/str(i),'extraction',state);assert result.returncode==0,result.stderr;assert result.stdout.splitlines()==['extraction','403']
def test_matching_active_trial_verdict_is_writable(tmp_path):
 result=run(tmp_path,'trial',active());assert result.returncode==0,result.stderr;assert result.stdout.splitlines()==['trial','201']
def test_valid_paid_license_remains_writable_despite_extraction_verdict(monkeypatch):
 import desktop.startup_verdict as verdict
 from desktop.entitlements import Entitlement
 monkeypatch.setattr(verdict,'peek_current_entitlement',lambda:Entitlement(state='paid',edition='personal',valid=True,mutations_allowed=True,reason='signed_license'))
 monkeypatch.setenv('GROWTHMAP_STARTUP_VERDICT_MODE','extraction');monkeypatch.setenv('GROWTHMAP_SESSION_TOKEN','x');nonce='N'*43;monkeypatch.setenv('GROWTHMAP_STARTUP_VERDICT_NONCE',nonce);monkeypatch.setenv('GROWTHMAP_STARTUP_VERDICT_MAC',hmac.new(b'x',f'growthmap-startup-v1:extraction:{nonce}'.encode(),hashlib.sha256).hexdigest())
 assert verdict.effective_entitlement().state=='paid'

def test_invalid_or_missing_verdict_cannot_make_trial_writable(monkeypatch,tmp_path):
 monkeypatch.setenv('GROWTHMAP_DESKTOP_MODE','1');monkeypatch.setenv('GROWTHMAP_SESSION_TOKEN','x');monkeypatch.setenv('GROWTHMAP_TRIAL_STATE_FILE',str(tmp_path/'trial.json'));(tmp_path/'trial.json').write_text(json.dumps(active()))
 from desktop.startup_verdict import effective_entitlement
 assert effective_entitlement().state=='extraction'
