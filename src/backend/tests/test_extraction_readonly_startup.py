import hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path

def test_expired_startup_preserves_database_bytes_mtime_and_schema(tmp_path):
 db=tmp_path/'readonly.db';c=sqlite3.connect(db);c.executescript('''CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at DATETIME,updated_at DATETIME);
 CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT,branch_id TEXT,title TEXT,summary TEXT,node_type TEXT,status TEXT,maturity TEXT,priority INTEGER,confidence FLOAT,description TEXT,rules_text TEXT,constraints_text TEXT,examples_text TEXT,questions_text TEXT,decision_notes TEXT,tags JSON,created_by TEXT,last_edited_by TEXT,position_x FLOAT,position_y FLOAT,workflow_status TEXT,file_paths JSON,created_at DATETIME,updated_at DATETIME);
 CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT,from_node_id TEXT,to_node_id TEXT,relation_type TEXT,weight FLOAT,note TEXT,is_mainline BOOLEAN,created_at DATETIME);
 CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT,block_type TEXT,content JSON,order_index INTEGER,created_by TEXT,created_at DATETIME,updated_at DATETIME);
 CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,description TEXT,source_node_id TEXT,status TEXT,created_at DATETIME);
 INSERT INTO projects VALUES('p','kept','','','root','active','{}','2020-01-01','2020-01-01');
 INSERT INTO nodes VALUES('root','p',NULL,'root title','','concept','active','seed',0,0.5,'','','','','','','[]','human','human',0,0,'draft','[]','2020-01-01','2020-01-01');
 INSERT INTO nodes VALUES('child','p',NULL,'child title','','idea','active','seed',0,0.5,'','','','','','','[]','human','human',0,0,'draft','[]','2020-01-01','2020-01-01');
 INSERT INTO edges VALUES('edge','p','root','child','child_of',1,'',1,'2020-01-01');
 INSERT INTO content_blocks VALUES('block','child','note','{"title":"legacy"}',0,'human','2020-01-01','2020-01-01');
 INSERT INTO branches VALUES('branch','p','legacy branch','','child','active','2020-01-01');''');c.commit();c.close()
 trial=tmp_path/'trial.json';trial.write_text(json.dumps({'schema_version':1,'installation_id':'test-installation','started_at':'2020-01-01T00:00:00+00:00','last_seen_at':'2020-01-01T00:00:00+00:00'}))
 before=(hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns,sqlite3.connect(db).execute("select group_concat(name,',') from sqlite_master where type='table'").fetchone()[0]);time.sleep(.01)
 code='''from fastapi.testclient import TestClient
from main import app
h={"Authorization":"Bearer t"}
with TestClient(app) as c:
 r=c.get('/api/projects',headers=h);assert r.status_code==200 and r.json()[0]['name']=='kept'
 tree=c.get('/api/nodes/root/subtree',headers=h);assert tree.status_code==200,tree.text
 body=tree.json();assert body['title']=='root title' and body['revision']==1 and body['children'][0]['title']=='child title' and body['children'][0]['content_blocks'][0]['content']['title']=='legacy'
 edges=c.get('/api/projects/p/edges',headers=h);assert edges.status_code==200 and edges.json()[0]['revision']==1
 blocks=c.get('/api/nodes/child/blocks',headers=h);assert blocks.status_code==200 and blocks.json()[0]['content']['title']=='legacy'
 branches=c.get('/api/projects/p/branches',headers=h);assert branches.status_code==200 and branches.json()[0]['name']=='legacy branch'
 exported=c.get('/api/projects/p/export',headers=h);assert exported.status_code==200,exported.text
 assert '# kept' in exported.text and 'root title' in exported.text and 'child title' in exported.text and 'legacy' in exported.text
 assert c.post('/api/projects',headers=h,json={'name':'no'}).status_code==403
'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_FRESH_INSTALL':'0','GROWTHMAP_DB_QUERY_ONLY':'1','GROWTHMAP_SESSION_TOKEN':'t','DATABASE_URL':f'sqlite+aiosqlite:///{db}','GROWTHMAP_LICENSE_FILE':str(tmp_path/'license.json'),'GROWTHMAP_TRIAL_STATE_FILE':str(trial)}
 r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
 after=(hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns,sqlite3.connect(db).execute("select group_concat(name,',') from sqlite_master where type='table'").fetchone()[0]);assert after==before

def test_query_only_export_rejects_malformed_content_without_detail_or_write(tmp_path):
 db=tmp_path/'malformed.db';c=sqlite3.connect(db);c.executescript('''CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at TEXT,updated_at TEXT);CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT,title TEXT,summary TEXT,node_type TEXT,status TEXT,maturity TEXT);CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT,from_node_id TEXT,to_node_id TEXT,relation_type TEXT);CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT,block_type TEXT,content JSON,order_index INTEGER);INSERT INTO projects VALUES('p','safe','','','root','active','{}','','');INSERT INTO nodes VALUES('root','p','Root','','concept','active','seed');INSERT INTO content_blocks VALUES('b','root','note','not-json',0);''');c.close()
 before=(hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns)
 code='''from fastapi.testclient import TestClient\nfrom main import app\nwith TestClient(app) as c:\n r=c.get('/api/projects/p/export',headers={'Authorization':'Bearer t'});assert r.status_code==409 and r.json()=={'detail':'Project data is not compatible with Markdown export'}\n assert c.get('/api/projects/p/export').status_code==401\n'''
 env={**os.environ,'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_DB_QUERY_ONLY':'1','GROWTHMAP_SESSION_TOKEN':'t','DATABASE_URL':f'sqlite+aiosqlite:///{db}'}
 r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
 assert (hashlib.sha256(db.read_bytes()).hexdigest(),db.stat().st_mtime_ns)==before

def test_query_only_export_does_not_convert_direct_type_error(monkeypatch):
 import pytest
 from api import routes
 def fail(_value):raise TypeError('unrelated decoder failure')
 monkeypatch.setattr(routes,'_decode_export_content',fail)
 with pytest.raises(TypeError,match='unrelated decoder failure'):routes._decode_export_content('{}')

def test_query_only_export_does_not_classify_unrelated_statement_errors():
 from sqlalchemy.exc import StatementError
 from api.routes import _is_json_deserialization_error
 for original in (ValueError('unrelated'),TypeError('unrelated')):
  assert _is_json_deserialization_error(StatementError('failed','select 1',(),original)) is False
