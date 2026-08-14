"""Canonical SQLite compatibility contract shared by migration and preflight."""
import re

CURRENT_USER_VERSION = 3
# table, column, declared type, NOT NULL, normalized default, additive v1 DDL
COLUMNS = (
    ("nodes", "branch_id", "VARCHAR(36)", False, None, "ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id)"),
    ("nodes", "workflow_status", "VARCHAR(20)", True, "draft", "ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("nodes", "file_paths", "JSON", False, "[]", "ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'"),
    ("provider_configs", "secret_env_key", "VARCHAR(128)", False, "", "ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''"),
    ("projects", "revision", "INTEGER", True, "1", "ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("nodes", "revision", "INTEGER", True, "1", "ALTER TABLE nodes ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("edges", "revision", "INTEGER", True, "1", "ALTER TABLE edges ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("content_blocks", "revision", "INTEGER", True, "1", "ALTER TABLE content_blocks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("branches", "revision", "INTEGER", True, "1", "ALTER TABLE branches ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
)
# Optional feature tables are not part of every supported authoring-only legacy
# database.  Their additive columns are enforced only when the table exists.
TABLE_CONDITIONAL_COLUMNS = (
    ("agent_grants", "persistent", "BOOLEAN", True, "0", "ALTER TABLE agent_grants ADD COLUMN persistent BOOLEAN NOT NULL DEFAULT 0"),
)
INDEX_SQL = "CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type = 'child_of' AND is_mainline = 1"
TRIGGERS = {
"trg_edges_one_mainline_insert": """CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1); END""",
"trg_edges_one_mainline_update": """CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id, relation_type, is_mainline ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1 AND id != OLD.id); END""",
"trg_edges_normalize_null_insert": """CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
"trg_edges_normalize_null_update": """CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight, note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
}
OBJECT_SQL = {"ux_edges_one_mainline_per_parent": INDEX_SQL, **TRIGGERS}

# affinity, NOT NULL, normalized declared default.
def _s(affinity, not_null=False, default=None): return (affinity, not_null, default)
# Branches retain a narrowly supported legacy declaration contract, with required
# historical values checked row-by-row. All other response-required identifiers
# and timestamps must be declared NOT NULL so future writes cannot create rows
# that fail response validation.
ROW_REQUIRED_NON_NULL = {
 "projects":("created_at","updated_at"), "nodes":("created_at","updated_at"),
 "edges":("created_at",), "content_blocks":("created_at","updated_at"),
 "branches":("id","project_id","name","description","status","created_at"),
}

ORM_READ_COLUMNS = {
 "projects": {
  "id":_s("TEXT",True),"name":_s("TEXT",True),"description":_s("TEXT"),"goal":_s("TEXT"),"root_node_id":_s("TEXT"),"status":_s("TEXT",True),"settings":_s("JSON"),"created_at":_s(("TEXT","NUMERIC"),True),"updated_at":_s(("TEXT","NUMERIC"),True),"revision":_s("INTEGER",True,"1")},
 "nodes": {
  "id":_s("TEXT",True),"project_id":_s("TEXT",True),"title":_s("TEXT",True),"summary":_s("TEXT"),"node_type":_s("TEXT",True),"status":_s("TEXT",True),"maturity":_s("TEXT",True),"priority":_s("INTEGER"),"confidence":_s("REAL"),"description":_s("TEXT"),"rules_text":_s("TEXT"),"constraints_text":_s("TEXT"),"examples_text":_s("TEXT"),"questions_text":_s("TEXT"),"decision_notes":_s("TEXT"),"tags":_s("JSON"),"workflow_status":_s("TEXT",True,"draft"),"file_paths":_s("JSON",False,"[]"),"branch_id":_s("TEXT"),"created_by":_s("TEXT"),"last_edited_by":_s("TEXT"),"position_x":_s("REAL"),"position_y":_s("REAL"),"created_at":_s(("TEXT","NUMERIC"),True),"updated_at":_s(("TEXT","NUMERIC"),True),"revision":_s("INTEGER",True,"1")},
 "edges": {
  "id":_s("TEXT",True),"project_id":_s("TEXT",True),"from_node_id":_s("TEXT",True),"to_node_id":_s("TEXT",True),"relation_type":_s("TEXT",True),"weight":_s("REAL",False,(None,"1.0","1")),"note":_s("TEXT",False,(None,"")),"is_mainline":_s(("INTEGER","NUMERIC"),True,(None,"0")),"created_at":_s(("TEXT","NUMERIC"),True),"revision":_s("INTEGER",True,"1")},
 "content_blocks": {
  "id":_s("TEXT",True),"node_id":_s("TEXT",True),"block_type":_s("TEXT",True),"content":_s("JSON",True),"order_index":_s("INTEGER",True),"created_by":_s("TEXT"),"created_at":_s(("TEXT","NUMERIC"),True),"updated_at":_s(("TEXT","NUMERIC"),True),"revision":_s("INTEGER",True,"1")},
 "branches": {
  "id":_s("TEXT",(False,True)),"project_id":_s("TEXT",(False,True)),"name":_s("TEXT",(False,True)),"description":_s("TEXT"),"source_node_id":_s("TEXT"),"status":_s("TEXT"),"created_at":_s(("TEXT","NUMERIC")),"revision":_s("INTEGER",True,"1")},
}


def sqlite_affinity(declared_type):
    value=str(declared_type or "").upper()
    if "INT" in value:return "INTEGER"
    if any(token in value for token in ("CHAR","CLOB","TEXT")):return "TEXT"
    if "BLOB" in value or not value:return "BLOB"
    if any(token in value for token in ("REAL","FLOA","DOUB")):return "REAL"
    if value=="JSON":return "JSON"
    return "NUMERIC"


def normalize_default(value):
    if value is None:return None
    value=str(value).strip()
    while len(value)>=2 and value[0]=='(' and value[-1]==')':value=value[1:-1].strip()
    if len(value)>=2 and value[0] in "'\"" and value[-1]==value[0]:value=value[1:-1].replace(value[0]*2,value[0])
    return value


def orm_column_problem(row, spec):
    if row is None:return "missing"
    affinities=spec[0] if isinstance(spec[0],tuple) else (spec[0],)
    nulls=spec[1] if isinstance(spec[1],tuple) else (spec[1],)
    if sqlite_affinity(row[2]) not in affinities:return "incompatible"
    if bool(row[3]) not in nulls:return "incompatible"
    defaults=spec[2] if isinstance(spec[2],tuple) else (spec[2],)
    return None if normalize_default(row[4]) in defaults else "incompatible"


def normalize_sql(sql):
    value=re.sub(r"\bIF\s+NOT\s+EXISTS\b","",sql or "",flags=re.I)
    value=re.sub(r"\s+"," ",value.strip()).lower()
    return re.sub(r"\s*([(),;=!])\s*",r"\1",value)


def column_matches(row,spec):
    return str(row[2]).upper()==spec[2] and bool(row[3])==spec[3] and normalize_default(row[4])==spec[4]
