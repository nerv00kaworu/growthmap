"""Canonical SQLite compatibility contract shared by migration and preflight."""
import re

CURRENT_USER_VERSION = 2
COLUMNS = (
    ("nodes", "branch_id", "VARCHAR(36)", False, None, "ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id)"),
    ("nodes", "workflow_status", "VARCHAR(20)", True, "draft", "ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("nodes", "file_paths", "JSON", False, "[]", "ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'"),
    # Existing fresh SQLAlchemy schemas historically omitted a server default;
    # the v2 ALTER path adds '' so legacy rows receive a deterministic value.
    ("provider_configs", "secret_env_key", "VARCHAR(128)", False, (None, ""), "ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''"),
    ("projects", "revision", "INTEGER", True, "1", "ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("nodes", "revision", "INTEGER", True, "1", "ALTER TABLE nodes ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("edges", "revision", "INTEGER", True, "1", "ALTER TABLE edges ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("content_blocks", "revision", "INTEGER", True, "1", "ALTER TABLE content_blocks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("branches", "revision", "INTEGER", True, "1", "ALTER TABLE branches ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
)
INDEX_SQL = "CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type = 'child_of' AND is_mainline = 1"
TRIGGERS = {
"trg_edges_one_mainline_insert": """CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1); END""",
"trg_edges_one_mainline_update": """CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id, relation_type, is_mainline ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1 AND id != OLD.id); END""",
"trg_edges_normalize_null_insert": """CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
"trg_edges_normalize_null_update": """CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight, note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
}
OBJECT_SQL = {"ux_edges_one_mainline_per_parent": INDEX_SQL, **TRIGGERS}


def normalize_sql(sql):
    value = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", sql or "", flags=re.I)
    value = re.sub(r"\s+", " ", value.strip()).lower()
    return re.sub(r"\s*([(),;=!])\s*", r"\1", value)


def normalize_default(value):
    if value is None:
        return None
    return str(value).strip("()").strip("'\"")


def column_matches(row, spec):
    expected_default=spec[4] if isinstance(spec[4],tuple) else (spec[4],)
    return str(row[2]).upper()==spec[2] and bool(row[3])==spec[3] and normalize_default(row[4]) in expected_default
