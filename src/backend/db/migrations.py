"""Ordered fail-closed SQLite schema migrations.

Migration-owned objects are introspected rather than created under broad exception
handlers. The caller supplies a transaction; ``user_version`` advances only after
all columns and objects validate.
"""
import os, re
from sqlalchemy import text

CURRENT_USER_VERSION = 2
COLUMNS = (
    ("nodes", "branch_id", "VARCHAR(36)", False, None, "ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id)"),
    ("nodes", "workflow_status", "VARCHAR(20)", True, "draft", "ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("nodes", "file_paths", "JSON", False, "[]", "ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'"),
    ("provider_configs", "secret_env_key", "VARCHAR(128)", False, None, "ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''"),
    ("projects", "revision", "INTEGER", True, "1", "ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("nodes", "revision", "INTEGER", True, "1", "ALTER TABLE nodes ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("edges", "revision", "INTEGER", True, "1", "ALTER TABLE edges ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("content_blocks", "revision", "INTEGER", True, "1", "ALTER TABLE content_blocks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("branches", "revision", "INTEGER", True, "1", "ALTER TABLE branches ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
)
READBACK_CORE_COLUMNS = (
    ("agent_readbacks","id","VARCHAR(36)",True,None),
    ("agent_readbacks","grant_id","VARCHAR(36)",True,None),
    ("agent_readbacks","project_id","VARCHAR(36)",True,None),
    ("agent_readbacks","target_node_id","VARCHAR(36)",False,None),
    ("agent_readbacks","commit_refs","JSON",True,None),("agent_readbacks","files","JSON",True,None),
    ("agent_readbacks","tests","JSON",True,None),("agent_readbacks","decisions","JSON",True,None),
    ("agent_readbacks","risks","JSON",True,None),("agent_readbacks","todos","JSON",True,None),
    ("agent_readbacks","evidence","JSON",True,None),("agent_readbacks","summary","TEXT",False,None),
    ("agent_readbacks","created_at","DATETIME",False,None),
)
READBACK_CREATE_SQL = """CREATE TABLE agent_readbacks (
 id VARCHAR(36) NOT NULL PRIMARY KEY,
 grant_id VARCHAR(36) NOT NULL REFERENCES agent_grants(id) ON DELETE CASCADE,
 project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 target_node_id VARCHAR(36) REFERENCES nodes(id) ON DELETE SET NULL,
 based_on_project_revision INTEGER NOT NULL DEFAULT '1',
 context_snapshot_digest VARCHAR(64) NOT NULL DEFAULT '',
 objective TEXT NOT NULL DEFAULT '', current_project_revision INTEGER NOT NULL DEFAULT '1',
 context_stale BOOLEAN NOT NULL DEFAULT '1',
 commit_refs JSON NOT NULL, files JSON NOT NULL, tests JSON NOT NULL, decisions JSON NOT NULL,
 risks JSON NOT NULL, todos JSON NOT NULL, evidence JSON NOT NULL, summary TEXT, created_at DATETIME
)"""
READBACK_INDEXES = {
 "ix_agent_readbacks_grant_id":"grant_id",
 "ix_agent_readbacks_project_id":"project_id",
}
READBACK_FKS = {("grant_id","agent_grants","id","CASCADE"),("project_id","projects","id","CASCADE"),("target_node_id","nodes","id","SET NULL")}
READBACK_COLUMNS = (
    ("agent_readbacks", "based_on_project_revision", "INTEGER", True, "1", "ALTER TABLE agent_readbacks ADD COLUMN based_on_project_revision INTEGER NOT NULL DEFAULT 1"),
    ("agent_readbacks", "context_snapshot_digest", "VARCHAR(64)", True, "", "ALTER TABLE agent_readbacks ADD COLUMN context_snapshot_digest VARCHAR(64) NOT NULL DEFAULT ''"),
    ("agent_readbacks", "objective", "TEXT", True, "", "ALTER TABLE agent_readbacks ADD COLUMN objective TEXT NOT NULL DEFAULT ''"),
    ("agent_readbacks", "current_project_revision", "INTEGER", True, "1", "ALTER TABLE agent_readbacks ADD COLUMN current_project_revision INTEGER NOT NULL DEFAULT 1"),
    ("agent_readbacks", "context_stale", "BOOLEAN", True, "1", "ALTER TABLE agent_readbacks ADD COLUMN context_stale BOOLEAN NOT NULL DEFAULT 1"),
)

INDEX_SQL = "CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type = 'child_of' AND is_mainline = 1"
TRIGGERS = {
"trg_edges_one_mainline_insert": """CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1); END""",
"trg_edges_one_mainline_update": """CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id, relation_type, is_mainline ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1 AND id != OLD.id); END""",
"trg_edges_normalize_null_insert": """CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
"trg_edges_normalize_null_update": """CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight, note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
}

def _norm(sql): return re.sub(r"\s+", " ", sql.strip()).replace("IF NOT EXISTS ", "").lower()
def _default(value): return None if value is None else str(value).strip("()").strip("'\"")

async def _validate_column(conn, table, name, expected_type, not_null, default):
    rows = (await conn.execute(text(f'PRAGMA table_info("{table}")'))).mappings().all()
    row = next((r for r in rows if r["name"] == name), None)
    if not row: return False
    if str(row["type"]).upper() != expected_type or bool(row["notnull"]) != not_null or _default(row["dflt_value"]) != default:
        raise RuntimeError(f"incompatible migration column {table}.{name}")
    return True

async def _validate_readback_fks(conn):
    actual={(r[3],r[2],r[4],str(r[6]).upper()) for r in (await conn.execute(text("PRAGMA foreign_key_list(agent_readbacks)"))).all()}
    if actual!=READBACK_FKS:raise RuntimeError("incompatible agent_readbacks foreign keys")

async def _validate_readback_index(conn,name,column):
    rows=(await conn.execute(text("PRAGMA index_list(agent_readbacks)"))).all();row=next((r for r in rows if r[1]==name),None)
    if not row:return False
    if bool(row[2]) or bool(row[4]):raise RuntimeError(f"incompatible migration index {name}")
    keys=[r for r in (await conn.execute(text(f'PRAGMA index_xinfo("{name}")'))).all() if r[5]]
    if len(keys)!=1 or keys[0][2]!=column or keys[0][1]<0:raise RuntimeError(f"incompatible migration index {name}")
    return True

async def migrate_sqlite(conn):
    version = int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
    if version > CURRENT_USER_VERSION: raise RuntimeError("database schema is newer than this application")
    if version < 1:
        for ordinal, spec in enumerate(COLUMNS, 1):
            if not await _validate_column(conn, *spec[:5]):
                await conn.execute(text(spec[5]))
            if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER") == str(ordinal):
                raise RuntimeError("injected migration failure")
        row = (await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='index' AND name='ux_edges_one_mainline_per_parent'"))).scalar()
        if row is None: await conn.execute(text(INDEX_SQL))
        elif _norm(row) != _norm(INDEX_SQL): raise RuntimeError("incompatible migration index ux_edges_one_mainline_per_parent")
        for name, sql in TRIGGERS.items():
            existing = (await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='trigger' AND name=:name"), {"name":name})).scalar()
            if existing is None: await conn.execute(text(sql))
            elif _norm(existing) != _norm(sql): raise RuntimeError(f"incompatible migration trigger {name}")
        for spec in COLUMNS: assert await _validate_column(conn, *spec[:5])
        await conn.execute(text("PRAGMA user_version=1"))
        version = 1
    if version < 2:
        # A savepoint forces Python's SQLite driver to keep DDL transactional.
        await conn.execute(text("SAVEPOINT growthmap_v2"))
        try:
            tables = {r[0] for r in (await conn.execute(text("SELECT name FROM sqlite_schema WHERE type='table'"))).all()}
            created="agent_readbacks" not in tables
            if created: await conn.execute(text(READBACK_CREATE_SQL))
            else:
                for spec in READBACK_CORE_COLUMNS:
                    if not await _validate_column(conn,*spec):raise RuntimeError(f"incomplete legacy readback core: {spec[1]}")
                await _validate_readback_fks(conn)
            for spec in READBACK_COLUMNS:
                if not await _validate_column(conn, *spec[:5]): await conn.execute(text(spec[5]))
            for spec in (*READBACK_CORE_COLUMNS,*[x[:5] for x in READBACK_COLUMNS]): assert await _validate_column(conn,*spec)
            await _validate_readback_fks(conn)
            for ordinal,(name,column) in enumerate(READBACK_INDEXES.items(),1):
                if not await _validate_readback_index(conn,name,column):await conn.execute(text(f"CREATE INDEX {name} ON agent_readbacks ({column})"))
                assert await _validate_readback_index(conn,name,column)
                if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_V2_AFTER")==str(ordinal):raise RuntimeError("injected v2 migration failure")
            await conn.execute(text("PRAGMA user_version=2"))
            await conn.execute(text("RELEASE SAVEPOINT growthmap_v2"))
        except Exception:
            await conn.execute(text("ROLLBACK TO SAVEPOINT growthmap_v2"));await conn.execute(text("RELEASE SAVEPOINT growthmap_v2"));raise
    final = int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
    if final != CURRENT_USER_VERSION: raise RuntimeError("migration version did not validate")
