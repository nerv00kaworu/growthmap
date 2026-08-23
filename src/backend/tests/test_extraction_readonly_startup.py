import hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path

import pytest

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

def _query_only_export_db(path, content):
 c=sqlite3.connect(path);c.executescript('''CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at TEXT,updated_at TEXT);CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT,branch_id TEXT,title TEXT,summary TEXT,node_type TEXT,status TEXT,maturity TEXT);CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT,from_node_id TEXT,to_node_id TEXT,relation_type TEXT);CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT,block_type TEXT,content JSON,order_index INTEGER);INSERT INTO projects VALUES('p','safe','','','root','active','{}','','');INSERT INTO projects VALUES('other','isolated','','','other-root','active','{}','','');INSERT INTO nodes VALUES('root','p',NULL,'Root','','concept','active','seed');INSERT INTO nodes VALUES('other-root','other',NULL,'Other','','concept','active','seed');INSERT INTO content_blocks VALUES('other-bad','other-root','note','not-json',0);''')
 c.execute("INSERT INTO content_blocks VALUES('b','root','note',?,0)",(content,));c.commit();c.close()


def _run_query_only_export(path, expected_status):
 before=(hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)
 code='''from fastapi.testclient import TestClient\nfrom main import app\nwith TestClient(app) as c:\n assert c.get('/api/projects/p/export').status_code==401\n r=c.get('/api/projects/p/export',headers={'Authorization':'Bearer t'});assert r.status_code==int(__import__('os').environ['EXPECTED']),r.text\n if r.status_code==409:assert r.json()=={'detail':'Project data is not compatible with Markdown export'}\n else:assert '# safe' in r.text and 'Root' in r.text\n'''
 env={**os.environ,'EXPECTED':str(expected_status),'GROWTHMAP_DESKTOP_MODE':'1','GROWTHMAP_DB_QUERY_ONLY':'1','GROWTHMAP_SESSION_TOKEN':'t','DATABASE_URL':f'sqlite+aiosqlite:///{path}'}
 r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True);assert r.returncode==0,r.stdout+r.stderr
 assert (hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)==before


@pytest.mark.parametrize('name,content',[('null',None),('scalar','42'),('list','[]'),('bytes',sqlite3.Binary(b'{"title":"bytes"}')),('malformed','not-json')])
def test_query_only_export_rejects_incompatible_content_without_detail_or_write(tmp_path,name,content):
 db=tmp_path/f'{name}.db';_query_only_export_db(db,content);_run_query_only_export(db,409)


def test_query_only_export_accepts_json_object_and_isolates_projects(tmp_path):
 db=tmp_path/'valid.db';_query_only_export_db(db,'{"title":"valid"}');_run_query_only_export(db,200)


def test_query_only_export_accepts_decoded_dict_directly(monkeypatch):
 import asyncio
 from api import routes
 monkeypatch.setenv('GROWTHMAP_DB_QUERY_ONLY','1')
 async def rows(_db,_project_id):
  return {'id':'p','name':'safe','description':'','goal':'','root_node_id':'root'},[{'id':'root','title':'Root','summary':'','maturity':'seed'}],[],[{'id':'b','node_id':'root','block_type':'note','content':{'title':'valid'},'order_index':0}]
 monkeypatch.setattr(routes,'_query_only_export_rows',rows)
 response=asyncio.run(routes.export_project('p',object()))
 assert 'valid' in response

def _patched_query_only_rows():
 async def rows(_db,_project_id):
  return {'id':'p','name':'safe','description':'','goal':'','root_node_id':'root'},[{'id':'root','title':'Root','summary':'','maturity':'seed'}],[],[{'id':'b','node_id':'root','block_type':'note','content':'{}','order_index':0}]
 return rows


def test_query_only_export_route_converts_actual_json_decode_error(monkeypatch):
 import asyncio
 from fastapi import HTTPException
 from api import routes
 monkeypatch.setenv('GROWTHMAP_DB_QUERY_ONLY','1')
 def fail(_value):raise json.JSONDecodeError('stored JSON failed','x',0)
 monkeypatch.setattr(routes,'_query_only_export_rows',_patched_query_only_rows());monkeypatch.setattr(routes,'_decode_export_content',fail)
 with pytest.raises(HTTPException) as caught:asyncio.run(routes.export_project('p',object()))
 assert caught.value.status_code==409 and caught.value.detail=='Project data is not compatible with Markdown export'


def test_query_only_export_route_propagates_direct_decoder_type_error(monkeypatch):
 import asyncio
 from api import routes
 monkeypatch.setenv('GROWTHMAP_DB_QUERY_ONLY','1')
 def fail(_value):raise TypeError('unrelated decoder failure')
 monkeypatch.setattr(routes,'_query_only_export_rows',_patched_query_only_rows());monkeypatch.setattr(routes,'_decode_export_content',fail)
 with pytest.raises(TypeError,match='unrelated decoder failure'):asyncio.run(routes.export_project('p',object()))

def test_query_only_export_does_not_classify_unrelated_statement_errors():
 from sqlalchemy.exc import StatementError
 from api.routes import _is_json_deserialization_error
 for original in (ValueError('unrelated'),TypeError('unrelated')):
  assert _is_json_deserialization_error(StatementError('failed','select 1',(),original)) is False

def test_query_only_export_route_propagates_direct_type_error(monkeypatch):
 import asyncio,pytest
 from api import routes
 async def fail(_db,_project_id):raise TypeError('injected direct failure')
 monkeypatch.setenv('GROWTHMAP_DB_QUERY_ONLY','1');monkeypatch.setattr(routes,'_query_only_export_rows',fail)
 with pytest.raises(TypeError,match='injected direct failure'):asyncio.run(routes.export_project('p',object()))

def test_query_only_export_route_propagates_unrelated_statement_errors(monkeypatch):
 import asyncio,pytest
 from sqlalchemy.exc import StatementError
 from api import routes
 monkeypatch.setenv('GROWTHMAP_DB_QUERY_ONLY','1')
 for original in (ValueError('unrelated'),TypeError('unrelated')):
  async def fail(_db,_project_id,_original=original):raise StatementError('failed','select 1',(),_original)
  monkeypatch.setattr(routes,'_query_only_export_rows',fail)
  with pytest.raises(StatementError) as caught:asyncio.run(routes.export_project('p',object()))
  assert caught.value.orig is original

def test_export_content_decoder_rejects_null_and_non_object_shapes_only_as_domain_errors():
 import pytest
 from api.routes import ExportContentCompatibilityError,_decode_export_content
 assert _decode_export_content('{}')=={} and _decode_export_content({'body':'ok'})=={'body':'ok'}
 for value in (None,[],1,'[]','null','1'):
  with pytest.raises(ExportContentCompatibilityError):_decode_export_content(value)
