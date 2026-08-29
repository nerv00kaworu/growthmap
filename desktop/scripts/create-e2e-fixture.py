"""Create a dependency-free canonical GrowthMap DB fixture in system temp."""
import os, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src/backend"))
from db.schema_contract import CURRENT_USER_VERSION, WORKSPACE_GRANT_INDEX_SQL, PROVIDER_SELECTION_TABLE_SQL

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
c.executescript(f"""
CREATE TABLE projects(id TEXT PRIMARY KEY NOT NULL,name TEXT NOT NULL,description TEXT,goal TEXT,root_node_id TEXT,status TEXT NOT NULL,settings JSON,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,source_node_id TEXT,name TEXT NOT NULL,description TEXT,status TEXT,created_at DATETIME,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE nodes(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,title TEXT NOT NULL,summary TEXT,node_type TEXT NOT NULL,status TEXT NOT NULL,maturity TEXT NOT NULL,priority INTEGER,confidence FLOAT,description TEXT,rules_text TEXT,constraints_text TEXT,examples_text TEXT,questions_text TEXT,decision_notes TEXT,tags JSON,workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft',file_paths JSON DEFAULT '[]',branch_id VARCHAR(36),created_by TEXT,last_edited_by TEXT,position_x FLOAT,position_y FLOAT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE edges(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,from_node_id TEXT NOT NULL,to_node_id TEXT NOT NULL,relation_type TEXT NOT NULL,weight FLOAT DEFAULT 1.0,note TEXT,is_mainline BOOLEAN NOT NULL,created_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY NOT NULL,node_id TEXT NOT NULL,block_type TEXT NOT NULL,content JSON NOT NULL,order_index INTEGER NOT NULL,created_by TEXT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE agent_grants(id TEXT PRIMARY KEY,token_prefix TEXT NOT NULL,token_salt TEXT NOT NULL,token_hash TEXT NOT NULL,project_id TEXT,permission TEXT NOT NULL,workspace_scope VARCHAR(20) NOT NULL DEFAULT 'legacy_project',mode VARCHAR(32),node_scope_id TEXT,branch_root_id TEXT,label TEXT NOT NULL,agent_identity TEXT NOT NULL,status TEXT NOT NULL,expires_at DATETIME,persistent BOOLEAN NOT NULL DEFAULT 0,revoked_at DATETIME,last_used_at DATETIME,created_at DATETIME);
CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT,node_id TEXT,actor_type TEXT,actor_id TEXT,action_type TEXT,payload JSON,created_at DATETIME);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT NOT NULL,provider_type VARCHAR(30) NOT NULL,endpoint TEXT,auth_type VARCHAR(20),secret_env_key VARCHAR(128) DEFAULT '',model_name TEXT,capabilities JSON,cost_level VARCHAR(10),enabled BOOLEAN,settings JSON,created_at DATETIME,updated_at DATETIME,revision INTEGER NOT NULL DEFAULT 1,secret_change_pending BOOLEAN NOT NULL DEFAULT 0,secret_change_claim VARCHAR(64),CONSTRAINT ck_provider_revision_safe CHECK (revision >= 1 AND revision <= 9007199254740991));
{PROVIDER_SELECTION_TABLE_SQL};
INSERT INTO provider_selection(singleton_id,provider_id,selection_revision,updated_at) VALUES(1,NULL,1,CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type='child_of' AND is_mainline=1;
{WORKSPACE_GRANT_INDEX_SQL};
CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1); END;
CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id,relation_type,is_mainline ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1 AND id!=OLD.id); END;
CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight,note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
CREATE TRIGGER trg_provider_revision_insert BEFORE INSERT ON provider_configs WHEN typeof(NEW.revision) != 'integer' OR NEW.revision < 1 OR NEW.revision > 9007199254740991 BEGIN SELECT RAISE(ABORT, 'provider revision out of range'); END;
CREATE TRIGGER trg_provider_revision_update BEFORE UPDATE OF revision ON provider_configs WHEN typeof(NEW.revision) != 'integer' OR NEW.revision < 1 OR NEW.revision > 9007199254740991 BEGIN SELECT RAISE(ABORT, 'provider revision out of range'); END;
PRAGMA user_version={CURRENT_USER_VERSION};
""")
created_at="2026-08-03T00:00:00+00:00"
c.execute("INSERT INTO projects(id,name,description,goal,root_node_id,status,settings,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",('fixture','Desktop Fixture','','','root','active','{}',1,created_at,created_at))
c.execute("INSERT INTO nodes(id,project_id,title,summary,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('root','fixture','Root','','concept','active','seed','draft',created_at,created_at,1))
c.execute("INSERT INTO nodes(id,project_id,title,summary,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('child','fixture','Child','','idea','active','seed','draft',created_at,created_at,1))
c.execute("INSERT INTO edges(id,project_id,from_node_id,to_node_id,relation_type,weight,note,is_mainline,created_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?)",('fixture-edge','fixture','root','child','child_of',1.0,'',1,created_at,1))
c.execute("INSERT INTO content_blocks(id,node_id,block_type,content,order_index,created_by,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?)",('block','root','note','{\"body\":\"fixture body\"}',0,'human',created_at,created_at,1));c.commit()
row=c.execute("SELECT id,name,status,revision,created_at,updated_at FROM projects WHERE id='fixture'").fetchone()
if row != ('fixture','Desktop Fixture','active',1,created_at,created_at): raise SystemExit("E2E fixture project contract mismatch")
if c.execute("PRAGMA user_version").fetchone()[0] != CURRENT_USER_VERSION: raise SystemExit("E2E fixture schema version mismatch")
if c.execute("SELECT singleton_id,provider_id,selection_revision FROM provider_selection").fetchone() != (1,None,1): raise SystemExit("E2E fixture provider selection mismatch")
c.close()
