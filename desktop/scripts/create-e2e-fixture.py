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
CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,title TEXT NOT NULL,summary TEXT DEFAULT '',node_type TEXT NOT NULL,status TEXT NOT NULL,maturity TEXT NOT NULL DEFAULT 'seed',priority INTEGER DEFAULT 0,confidence REAL DEFAULT 0.5,description TEXT DEFAULT '',rules_text TEXT DEFAULT '',constraints_text TEXT DEFAULT '',examples_text TEXT DEFAULT '',questions_text TEXT DEFAULT '',decision_notes TEXT DEFAULT '',tags JSON DEFAULT '[]',workflow_status TEXT NOT NULL DEFAULT 'draft',file_paths JSON DEFAULT '[]',branch_id TEXT,created_by TEXT DEFAULT 'human',last_edited_by TEXT DEFAULT 'human',position_x REAL DEFAULT 0,position_y REAL DEFAULT 0,created_at TEXT,updated_at TEXT,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT,from_node_id TEXT,to_node_id TEXT,relation_type TEXT,is_mainline INTEGER DEFAULT 0,weight REAL DEFAULT 1,note TEXT DEFAULT '',revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT,block_type TEXT,content JSON,order_index INTEGER,created_by TEXT DEFAULT 'human',created_at TEXT,updated_at TEXT,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT,actor_type TEXT,action_type TEXT,created_at TEXT);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER,secret_env_key TEXT DEFAULT '');
CREATE TABLE agent_grants(id VARCHAR(36) PRIMARY KEY,token_prefix VARCHAR(20),token_salt VARCHAR(64),token_hash VARCHAR(128),project_id VARCHAR(36),permission VARCHAR(10),node_scope_id VARCHAR(36),branch_root_id VARCHAR(36),label VARCHAR(120),agent_identity VARCHAR(120),status VARCHAR(12),expires_at DATETIME,revoked_at DATETIME,last_used_at DATETIME,created_at DATETIME);
CREATE TABLE agent_readbacks(id VARCHAR(36) NOT NULL PRIMARY KEY,grant_id VARCHAR(36) NOT NULL REFERENCES agent_grants(id) ON DELETE CASCADE,project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,target_node_id VARCHAR(36) REFERENCES nodes(id) ON DELETE SET NULL,based_on_project_revision INTEGER NOT NULL DEFAULT '1',context_snapshot_digest VARCHAR(64) NOT NULL DEFAULT '',objective TEXT NOT NULL DEFAULT '',current_project_revision INTEGER NOT NULL DEFAULT '1',context_stale BOOLEAN NOT NULL DEFAULT '1',commit_refs JSON NOT NULL,files JSON NOT NULL,tests JSON NOT NULL,decisions JSON NOT NULL,risks JSON NOT NULL,todos JSON NOT NULL,evidence JSON NOT NULL,summary TEXT,created_at DATETIME);
CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id);
CREATE INDEX ix_agent_readbacks_project_id ON agent_readbacks(project_id);
CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type='child_of' AND is_mainline=1;
CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1); END;
CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id,relation_type,is_mainline ON edges WHEN NEW.relation_type='child_of' AND NEW.is_mainline=1 BEGIN SELECT RAISE(ABORT,'duplicate mainline for parent') WHERE EXISTS(SELECT 1 FROM edges WHERE from_node_id=NEW.from_node_id AND relation_type='child_of' AND is_mainline=1 AND id!=OLD.id); END;
CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight,note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight=COALESCE(weight,1.0),note=COALESCE(note,'') WHERE id=NEW.id; END;
PRAGMA user_version=2;
""")
project_id="11111111-1111-4111-8111-111111111111"; root_id="22222222-2222-4222-8222-222222222222"; now="2026-07-30T00:00:00+00:00"
c.execute("INSERT INTO projects(id,name,description,goal,root_node_id,status,settings,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,1)",(project_id,"Desktop Fixture","","",root_id,"active","{}",now,now))
c.execute("INSERT INTO nodes(id,project_id,title,summary,node_type,status,maturity,priority,confidence,description,rules_text,constraints_text,examples_text,questions_text,decision_notes,tags,workflow_status,file_paths,created_by,last_edited_by,position_x,position_y,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",(root_id,project_id,"Desktop Fixture Root","","root","active","seed",0,0.5,"","","","","","","[]","draft","[]","human","human",0,0,now,now))
grant_id="33333333-3333-4333-8333-333333333333"; stale_grant_id="66666666-6666-4666-8666-666666666666"
for gid,prefix in [(grant_id,"gm_seed"),(stale_grant_id,"gm_stale")]:c.execute("INSERT INTO agent_grants(id,token_prefix,token_salt,token_hash,project_id,permission,label,agent_identity,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(gid,prefix,"salt","hash",project_id,"propose","Packaged fixture agent","fixture-agent","active","2099-01-01T00:00:00+00:00",now))
readback_sql="""INSERT INTO agent_readbacks(id,grant_id,project_id,target_node_id,based_on_project_revision,context_snapshot_digest,objective,current_project_revision,context_stale,commit_refs,files,tests,decisions,risks,todos,evidence,summary,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
evidence=("[\"abc123\"]","[\"src/feature.py\"]",'[{"name":"packaged integration","status":"passed"}]','["reuse strict v1 wire"]','["platform availability"]','["fresh review"]','[{"name":"diff","status":"verified","detail":"clean"}]')
for readback_id,stale,current,summary in [("44444444-4444-4444-8444-444444444444",0,1,"Packaged current implementation"),("55555555-5555-4555-8555-555555555555",1,2,"Packaged stale implementation")]:
 c.execute(readback_sql,(readback_id,stale_grant_id if stale else grant_id,project_id,root_id,1,"a"*64,"ship",current,stale,*evidence,summary,now))
c.commit();c.close()
