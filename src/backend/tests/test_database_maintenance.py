import os, sqlite3
from pathlib import Path
import pytest
from desktop import database_maintenance as dm

def fixture(path):
 c=sqlite3.connect(path);c.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT,created_at TEXT,updated_at TEXT);CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT,node_type TEXT,status TEXT,maturity TEXT);CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),from_node_id TEXT REFERENCES nodes(id),to_node_id TEXT REFERENCES nodes(id),relation_type TEXT);CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),block_type TEXT,content TEXT,order_index INTEGER);CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),actor_type TEXT,action_type TEXT,created_at TEXT);CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER);""");c.execute("insert into projects values('p','x','active','','')");c.commit();c.close()

def test_rejects_trigger_view_and_oversize(tmp_path,monkeypatch):
 for sql in ["CREATE VIEW evil AS SELECT * FROM projects","CREATE TRIGGER evil AFTER INSERT ON projects BEGIN SELECT 1; END"]:
  p=tmp_path/(str(abs(hash(sql)))+'.db');fixture(p);c=sqlite3.connect(p);c.execute(sql);c.close()
  with pytest.raises(ValueError,match='unapproved'):dm.validate(p)
 p=tmp_path/'large.db';fixture(p);monkeypatch.setattr(dm,'MAX_BYTES',100)
 with pytest.raises(ValueError,match='size'):dm.validate(p)

def test_validated_snapshot_rejects_hardlink_and_uses_combined_validation(tmp_path):
 p=tmp_path/'a.db';fixture(p);hard=tmp_path/'hard.db';os.link(p,hard)
 with pytest.raises(ValueError,match='single-link'):dm.validated_snapshot(hard,tmp_path/'out.db')
