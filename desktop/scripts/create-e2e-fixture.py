"""Create a dependency-free canonical GrowthMap DB fixture in system temp."""
import os, sqlite3, sys, tempfile
from pathlib import Path

def fixture_output(argument: str) -> Path:
    output=Path(argument).resolve(); temp_root=Path(tempfile.gettempdir()).resolve()
    if not output.is_relative_to(temp_root) or "src/backend/tests" in output.as_posix():
        raise SystemExit("E2E fixture path must be inside the system temp directory")
    if not output.name.startswith("fixture") or output.suffix.lower() not in {".db",".sqlite"}:
        raise SystemExit("E2E fixture filename must start with 'fixture' and end in .db or .sqlite")
    if output.exists(): raise SystemExit("E2E fixture output must be a fresh path")
    output.parent.mkdir(parents=True,exist_ok=True); return output

if len(sys.argv)!=2: raise SystemExit("usage: create-e2e-fixture.py TEMP_FIXTURE_PATH")
out=fixture_output(sys.argv[1]); c=sqlite3.connect(out)
# Canonical fixture surface required by desktop validation and schema preflight.
c.executescript("""
CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT DEFAULT '',goal TEXT DEFAULT '',root_node_id TEXT,status TEXT NOT NULL DEFAULT 'active',settings JSON DEFAULT '{}',created_at TEXT,updated_at TEXT,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT,source_node_id TEXT,name TEXT,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,title TEXT NOT NULL,summary TEXT DEFAULT '',node_type TEXT NOT NULL,status TEXT NOT NULL,maturity TEXT,branch_id VARCHAR(36),workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft',file_paths JSON DEFAULT '[]',revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT,from_node_id TEXT,to_node_id TEXT,relation_type TEXT,is_mainline INTEGER DEFAULT 0,weight REAL DEFAULT 1,note TEXT DEFAULT '',revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT,block_type TEXT,content JSON,order_index INTEGER,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT,actor_type TEXT,action_type TEXT,created_at TEXT);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER,secret_env_key VARCHAR(128) DEFAULT '');
CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type='child_of' AND is_mainline=1;
CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1); END;
CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id,relation_type,is_mainline ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1 AND id!=OLD.id); END;
CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight,note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
PRAGMA user_version=2;
""")
created_at="2026-08-03T00:00:00+00:00"
c.execute("INSERT INTO projects(id,name,status,revision,created_at,updated_at) VALUES(?,?,?,?,?,?)",('fixture','Desktop Fixture','active',1,created_at,created_at));c.commit()
row=c.execute("SELECT id,name,status,revision,created_at,updated_at FROM projects WHERE id='fixture'").fetchone()
if row != ('fixture','Desktop Fixture','active',1,created_at,created_at): raise SystemExit("E2E fixture project contract mismatch")
c.close()
