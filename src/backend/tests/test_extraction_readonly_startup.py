import hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path

def test_expired_startup_preserves_database_bytes_mtime_and_schema(tmp_path):
 db=tmp_path/'readonly.db';c=sqlite3.connect(db);c.executescript('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at DATETIME,updated_at DATETIME); INSERT INTO projects VALUES("p","kept","","",NULL,"active","{}","2020-01-01","2020-01-01");');c.commit();c.close()
 trial=tmp_path/'trial.json';trial.write_text(json.dumps({'schema_version':1,'installation_id':'test-installation','started_at':'2020-01-01T00:00:00+00:00','last_seen_at':'2020-01-01T00:00:00+00:00'}))
 before=(hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns,sqlite3.connect(db).execute("select group_concat(name,',') from sqlite_master where type='table'").fetchone()[0]);time.sleep(.01)
 code='''from fastapi.testclient import TestClient\nfrom main import app\nh={"Authorization":"Bearer t"}\nwith TestClient(app) as c:\n r=c.get('/api/projects',headers=h);assert r.status_code==200 and r.json()[0]['name']=='kept'\n assert c.post('/api/projects',headers=h,json={'name':'no'}).status_code==403\n'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'0','GROWTHMAP_DB_QUERY_ONLY':'1','GROWTHMAP_SESSION_TOKEN':'t','DATABASE_URL':f'sqlite+aiosqlite:///{db}','GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(trial)}
 r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
 after=(hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns,sqlite3.connect(db).execute("select group_concat(name,',') from sqlite_master where type='table'").fetchone()[0]);assert after==before
