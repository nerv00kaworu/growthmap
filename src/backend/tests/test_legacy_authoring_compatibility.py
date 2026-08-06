import os, sqlite3, subprocess, sys
from pathlib import Path


LEGACY_SCHEMA = """
CREATE TABLE projects(id TEXT PRIMARY KEY NOT NULL,name TEXT NOT NULL,description TEXT,goal TEXT,root_node_id TEXT,status TEXT NOT NULL,settings JSON,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL);
CREATE TABLE nodes(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,branch_id VARCHAR(36),title TEXT NOT NULL,summary TEXT,node_type TEXT NOT NULL,status TEXT NOT NULL,maturity TEXT NOT NULL,priority INTEGER,confidence FLOAT,description TEXT,rules_text TEXT,constraints_text TEXT,examples_text TEXT,questions_text TEXT,decision_notes TEXT,tags JSON,created_by TEXT,last_edited_by TEXT,position_x FLOAT,position_y FLOAT,workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft',file_paths JSON DEFAULT '[]',created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL);
CREATE TABLE edges(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,from_node_id TEXT NOT NULL,to_node_id TEXT NOT NULL,relation_type TEXT NOT NULL,weight FLOAT,note TEXT,is_mainline BOOLEAN NOT NULL,created_at DATETIME NOT NULL);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY NOT NULL,node_id TEXT NOT NULL,block_type TEXT NOT NULL,content JSON NOT NULL,order_index INTEGER NOT NULL,created_by TEXT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL);
CREATE TABLE suggestions(id TEXT PRIMARY KEY,project_id TEXT,target_node_id TEXT,action_type TEXT,status TEXT,payload JSON,provider_id TEXT,provider_model TEXT,cost_estimate FLOAT,created_at DATETIME,reviewed_at DATETIME,reviewed_by TEXT);
CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT,node_id TEXT,actor_type TEXT,actor_id TEXT,action_type TEXT,payload JSON,created_at DATETIME);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT NOT NULL,provider_type TEXT,endpoint TEXT,auth_type TEXT,secret_env_key VARCHAR(128) DEFAULT '',model_name TEXT,capabilities JSON,cost_level TEXT,enabled BOOLEAN,settings JSON,created_at DATETIME,updated_at DATETIME);
CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT,name TEXT NOT NULL,description TEXT,source_node_id TEXT,status TEXT,created_at DATETIME);
INSERT INTO projects VALUES('p','Legacy Project','kept description','kept goal','root','active','{}','2020-01-01','2020-01-01');
INSERT INTO nodes VALUES('root','p',NULL,'Root','','concept','active','seed',0,0.5,'','','','','','','[]','human','human',0,0,'draft','[]','2020-01-01','2020-01-01');
INSERT INTO nodes VALUES('child','p',NULL,'Child','kept summary','idea','active','seed',0,0.5,'','','','','','','[]','human','human',0,0,'draft','[]','2020-01-01','2020-01-01');
INSERT INTO edges VALUES('edge','p','root','child','child_of',1,'',1,'2020-01-01');
INSERT INTO content_blocks VALUES('block','child','note','{"title":"Kept block","body":"kept body"}',0,'human','2020-01-01','2020-01-01');
PRAGMA user_version=1;
"""


def test_version_one_legacy_db_upgrades_then_project_node_reads_and_markdown_export_work(tmp_path):
    db=tmp_path/'synthetic-legacy.db';connection=sqlite3.connect(db);connection.executescript(LEGACY_SCHEMA);connection.commit();connection.close()
    code='''from fastapi.testclient import TestClient\nfrom main import app\nwith TestClient(app) as c:\n p=c.get('/api/projects/p');assert p.status_code==200,p.text;assert p.json()['revision']==1 and p.json()['name']=='Legacy Project'\n n=c.get('/api/nodes/child');assert n.status_code==200,n.text;assert n.json()['revision']==1 and n.json()['summary']=='kept summary'\n nodes=c.get('/api/projects/p/nodes');assert nodes.status_code==200,nodes.text;assert len(nodes.json())==2 and all(x['revision']==1 for x in nodes.json())\n md=c.get('/api/projects/p/export');assert md.status_code==200,md.text;assert '# Legacy Project' in md.text and 'Child' in md.text and 'kept body' in md.text\n'''
    env={**os.environ,'DATABASE_URL':f'sqlite+aiosqlite:///{db}','APP_ENV':'test'}
    for _ in range(2):
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True)
        assert result.returncode==0,result.stdout+result.stderr
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()==(2,)
        assert {row[1] for row in connection.execute('PRAGMA table_info(projects)')} >= {'revision'}
        assert {row[1] for row in connection.execute('PRAGMA table_info(nodes)')} >= {'revision'}
        assert connection.execute('SELECT count(*) FROM projects').fetchone()==(1,)
        assert connection.execute('SELECT count(*) FROM nodes').fetchone()==(2,)
        assert connection.execute('SELECT count(*) FROM edges').fetchone()==(1,)
        assert connection.execute('SELECT count(*) FROM content_blocks').fetchone()==(1,)
        assert connection.execute("SELECT name,description,goal,revision FROM projects WHERE id='p'").fetchone()==('Legacy Project','kept description','kept goal',1)
