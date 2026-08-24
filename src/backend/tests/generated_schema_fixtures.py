"""Deterministic, non-user SQLite histories for the v12 upgrade contract.

Every database is created from SQL at the caller's path.  No application DB
path, environment default, binary template, or user data is read.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

STAMP = "2026-08-24T00:00:00+00:00"
PROJECT = "fixture-project-00000000-0000-0000-0000-000000000001"
PROVIDER = "fixture-provider-0000000-0000-0000-0000-000000000001"
GRANT = "fixture-grant-000000000-0000-0000-0000-000000000001"

CORE_SQL = """
CREATE TABLE projects(id TEXT PRIMARY KEY NOT NULL,name TEXT NOT NULL,description TEXT,goal TEXT,root_node_id TEXT,status TEXT NOT NULL,settings JSON,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,source_node_id TEXT,name TEXT NOT NULL,description TEXT,status TEXT,created_at DATETIME,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE nodes(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,title TEXT NOT NULL,summary TEXT,node_type TEXT NOT NULL,status TEXT NOT NULL,maturity TEXT NOT NULL,priority INTEGER,confidence FLOAT,description TEXT,rules_text TEXT,constraints_text TEXT,examples_text TEXT,questions_text TEXT,decision_notes TEXT,tags JSON,workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft',file_paths JSON DEFAULT '[]',branch_id VARCHAR(36),created_by TEXT,last_edited_by TEXT,position_x FLOAT,position_y FLOAT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE edges(id TEXT PRIMARY KEY NOT NULL,project_id TEXT NOT NULL,from_node_id TEXT NOT NULL,to_node_id TEXT NOT NULL,relation_type TEXT NOT NULL,weight FLOAT DEFAULT 1.0,note TEXT,is_mainline BOOLEAN NOT NULL,created_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY NOT NULL,node_id TEXT NOT NULL,block_type TEXT NOT NULL,content JSON NOT NULL,order_index INTEGER NOT NULL,created_by TEXT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT,node_id TEXT,actor_type TEXT,actor_id TEXT,action_type TEXT,payload JSON,created_at DATETIME);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER,secret_env_key VARCHAR(128) DEFAULT '',revision INTEGER NOT NULL DEFAULT 1,secret_change_pending BOOLEAN NOT NULL DEFAULT 0,secret_change_claim VARCHAR(64));
"""

GRANT_SQL = """CREATE TABLE agent_grants(
id TEXT PRIMARY KEY,token_prefix TEXT NOT NULL,token_salt TEXT NOT NULL,token_hash TEXT NOT NULL,
project_id TEXT,permission TEXT NOT NULL,workspace_scope VARCHAR(20) NOT NULL DEFAULT 'legacy_project',mode VARCHAR(32),
node_scope_id TEXT,branch_root_id TEXT,label TEXT NOT NULL,agent_identity TEXT NOT NULL,status TEXT NOT NULL,
expires_at DATETIME,persistent BOOLEAN NOT NULL DEFAULT 0,revoked_at DATETIME,last_used_at DATETIME,created_at DATETIME);
"""


def _objects(c: sqlite3.Connection, grants: bool) -> None:
    from db.schema_contract import INDEXES, TRIGGERS
    c.execute(INDEXES["ux_edges_one_mainline_per_parent"])
    if grants:
        c.execute(INDEXES["ux_agent_grants_one_active_workspace"])
    for sql in TRIGGERS.values():
        c.execute(sql)


def _rows(c: sqlite3.Connection) -> None:
    c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)", (PROJECT,"Generated Fixture","",None,"fixture-node-root","active","{}",STAMP,STAMP,7))
    c.execute("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?)", ("fixture-node-root",PROJECT,"Root","concept","active","seed","draft",STAMP,STAMP,3))
    c.execute("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?)", ("fixture-node-child",PROJECT,"Child","idea","active","seed","draft",STAMP,STAMP,4))
    c.execute("INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?,?)", ("fixture-edge",PROJECT,"fixture-node-root","fixture-node-child","child_of",1.0,"",1,STAMP,5))
    c.execute("INSERT INTO content_blocks VALUES(?,?,?,?,?,?,?,?,?)", ("fixture-block","fixture-node-root","note",'{"body":"generated fixture"}',0,"fixture",STAMP,STAMP,6))
    c.execute("INSERT INTO provider_configs VALUES(?,?,?,?,?,?,?,?,?)", (PROVIDER,"Generated Provider","openai","fixture-model",1,"FIXTURE_API_KEY",9,0,None))


def _canonical(c: sqlite3.Connection, grants: bool = False) -> None:
    from db.schema_contract import CURRENT_USER_VERSION, PROVIDER_SELECTION_TABLE_SQL
    c.executescript(CORE_SQL)
    if grants: c.executescript(GRANT_SQL)
    c.execute(PROVIDER_SELECTION_TABLE_SQL)
    _objects(c, grants)
    _rows(c)
    c.execute("INSERT INTO provider_selection VALUES(1,NULL,1,?)", (STAMP,))
    if grants:
        c.execute("INSERT INTO agent_grants(id,token_prefix,token_salt,token_hash,project_id,permission,workspace_scope,mode,label,agent_identity,status,expires_at,persistent,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (GRANT,"fixture-prefix","fixture-salt","fixture-hash",PROJECT,"propose","legacy_project","review_first","Generated grant","fixture-agent","active","2030-01-01T00:00:00+00:00",0,STAMP))
    c.execute(f"PRAGMA user_version={CURRENT_USER_VERSION}")


def _drop(c: sqlite3.Connection, table: str, *columns: str) -> None:
    for column in columns: c.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')


def generate(path: Path, variant: str) -> Path:
    """Create one fresh fixture under a caller-owned temporary directory."""
    path = Path(path).resolve()
    if path.exists(): raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    try:
        # Keep the optional Agent table in every post-Agent-Port history/current
        # fixture.  The v2 baseline intentionally proves it was genuinely absent.
        grants = variant != "v2"
        _canonical(c, grants)
        if variant == "v12": pass
        elif variant == "v2":
            c.execute("DROP TABLE provider_selection")
            c.execute("DROP TRIGGER trg_provider_revision_insert"); c.execute("DROP TRIGGER trg_provider_revision_update")
            _drop(c,"provider_configs","revision","secret_change_pending","secret_change_claim")
            for table in ("projects","nodes","edges","content_blocks","branches"): _drop(c,table,"revision")
            c.execute("PRAGMA user_version=2")
        elif variant in ("grant_nullable_legacy", "grant_not_null_missing"):
            c.execute("DROP INDEX ux_agent_grants_one_active_workspace")
            _drop(c,"agent_grants","persistent","workspace_scope","mode")
            if variant == "grant_not_null_missing":
                c.execute("ALTER TABLE agent_grants RENAME COLUMN expires_at TO old_expiry")
                c.execute("ALTER TABLE agent_grants ADD COLUMN expires_at DATETIME NOT NULL DEFAULT '2030-01-01T00:00:00+00:00'")
                c.execute("UPDATE agent_grants SET expires_at=old_expiry")
                c.execute("ALTER TABLE agent_grants DROP COLUMN old_expiry")
            c.execute("DROP TABLE provider_selection")
            c.execute("PRAGMA user_version=2")
        elif variant == "v8_no_provider_revision":
            c.execute("DROP TRIGGER trg_provider_revision_insert"); c.execute("DROP TRIGGER trg_provider_revision_update")
            _drop(c,"provider_configs","revision","secret_change_pending","secret_change_claim")
            c.execute("DROP TABLE provider_selection"); c.execute("PRAGMA user_version=8")
        elif variant == "v9_provider_revision":
            c.execute("DROP TABLE provider_selection"); c.execute("PRAGMA user_version=9")
        elif variant == "v11_no_selection":
            c.execute("DROP TABLE provider_selection"); c.execute("PRAGMA user_version=11")
        elif variant == "newer_v13": c.execute("PRAGMA user_version=13")
        elif variant == "bad_column":
            c.execute("ALTER TABLE projects DROP COLUMN settings"); c.execute("ALTER TABLE projects ADD COLUMN settings INTEGER")
        elif variant == "missing_object": c.execute("DROP TRIGGER trg_edges_normalize_null_insert")
        elif variant == "forged_object":
            c.execute("DROP TRIGGER trg_edges_normalize_null_insert")
            c.execute("CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges BEGIN SELECT 1; END")
        elif variant == "bad_selection_table":
            c.execute("DROP TABLE provider_selection"); c.execute("CREATE TABLE provider_selection(singleton_id INTEGER PRIMARY KEY,provider_id TEXT,selection_revision INTEGER,updated_at TEXT)")
        elif variant == "bad_selection_missing_row": c.execute("DELETE FROM provider_selection")
        elif variant == "bad_selection_row": c.execute("UPDATE provider_selection SET provider_id='missing-provider'")
        else: raise ValueError(f"unknown fixture variant: {variant}")
        c.commit()
    except BaseException:
        c.close(); path.unlink(missing_ok=True); raise
    else: c.close()
    return path


def logical_snapshot(path: Path):
    """Stable DDL/data snapshot, intentionally excluding volatile file headers."""
    c=sqlite3.connect(path)
    try:
        schema=tuple(c.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type,name"))
        tables=[row[0] for row in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows=tuple((table,tuple(c.execute(f'SELECT * FROM "{table}" ORDER BY rowid'))) for table in tables)
        return (c.execute("PRAGMA user_version").fetchone()[0],schema,rows)
    finally: c.close()
