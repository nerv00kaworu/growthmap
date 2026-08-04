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

# Every column selected by the four ORM entities used by ordinary authoring
# reads and writable Markdown export. Types are normalized to SQLite affinity;
# legacy VARCHAR/TEXT and DATETIME/TEXT declarations are intentionally accepted.
ORM_READ_COLUMNS = {
    "projects": {
        "id":"TEXT", "name":"TEXT", "description":"TEXT", "goal":"TEXT",
        "root_node_id":"TEXT", "status":"TEXT", "settings":"JSON",
        "created_at":("TEXT","NUMERIC"), "updated_at":("TEXT","NUMERIC"), "revision":"INTEGER",
    },
    "nodes": {
        "id":"TEXT", "project_id":"TEXT", "title":"TEXT", "summary":"TEXT",
        "node_type":"TEXT", "status":"TEXT", "maturity":"TEXT", "priority":"INTEGER",
        "confidence":"REAL", "description":"TEXT", "rules_text":"TEXT",
        "constraints_text":"TEXT", "examples_text":"TEXT", "questions_text":"TEXT",
        "decision_notes":"TEXT", "tags":"JSON", "workflow_status":"TEXT",
        "file_paths":"JSON", "branch_id":"TEXT", "created_by":"TEXT",
        "last_edited_by":"TEXT", "position_x":"REAL", "position_y":"REAL",
        "created_at":("TEXT","NUMERIC"), "updated_at":("TEXT","NUMERIC"), "revision":"INTEGER",
    },
    "edges": {
        "id":"TEXT", "project_id":"TEXT", "from_node_id":"TEXT", "to_node_id":"TEXT",
        "relation_type":"TEXT", "weight":"REAL", "note":"TEXT", "is_mainline":("INTEGER","NUMERIC"),
        "created_at":("TEXT","NUMERIC"), "revision":"INTEGER",
    },
    "content_blocks": {
        "id":"TEXT", "node_id":"TEXT", "block_type":"TEXT", "content":"JSON",
        "order_index":"INTEGER", "created_by":"TEXT", "created_at":("TEXT","NUMERIC"),
        "updated_at":("TEXT","NUMERIC"), "revision":"INTEGER",
    },
}


def sqlite_affinity(declared_type):
    value=str(declared_type or "").upper()
    if "INT" in value:return "INTEGER"
    if any(token in value for token in ("CHAR","CLOB","TEXT")):return "TEXT"
    if "BLOB" in value or not value:return "BLOB"
    if any(token in value for token in ("REAL","FLOA","DOUB")):return "REAL"
    if value=="JSON":return "JSON"
    return "NUMERIC"


def orm_column_problem(row, expected):
    if row is None:return "missing"
    allowed=expected if isinstance(expected,tuple) else (expected,)
    return None if sqlite_affinity(row[2]) in allowed else "incompatible"


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
