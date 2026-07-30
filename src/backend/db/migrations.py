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
READBACK_COLUMNS = (
    ("agent_readbacks", "based_on_project_revision", "INTEGER", True, "1", "ALTER TABLE agent_readbacks ADD COLUMN based_on_project_revision INTEGER NOT NULL DEFAULT 1"),
    ("agent_readbacks", "context_snapshot_digest", "VARCHAR(64)", True, "", "ALTER TABLE agent_readbacks ADD COLUMN context_snapshot_digest VARCHAR(64) NOT NULL DEFAULT ''"),
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
        tables = {r[0] for r in (await conn.execute(text("SELECT name FROM sqlite_schema WHERE type='table'"))).all()}
        if "agent_readbacks" in tables:
            for spec in READBACK_COLUMNS:
                if not await _validate_column(conn, *spec[:5]): await conn.execute(text(spec[5]))
            for spec in READBACK_COLUMNS: assert await _validate_column(conn, *spec[:5])
        await conn.execute(text("PRAGMA user_version=2"))
    final = int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
    if final != CURRENT_USER_VERSION: raise RuntimeError("migration version did not validate")
