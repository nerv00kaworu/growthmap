"""Canonical SQLite compatibility contract shared by migration and preflight."""
import re

# v5 applies the owner-approved legacy policy for ambiguous child_of mainlines:
# every mainline in a parent group containing 2+ mainlines is demoted. This is
# deliberately done before the one-mainline unique index is created.
# v9 adds the monotonic provider authority revision. A version bump is required
# so already-valid v8 databases are migrated instead of being rejected at startup.
CURRENT_USER_VERSION = 12
# table, column, declared type, NOT NULL, normalized default, additive v1 DDL
COLUMNS = (
    ("nodes", "branch_id", "VARCHAR(36)", False, None, "ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id)"),
    ("nodes", "workflow_status", "VARCHAR(20)", True, "draft", "ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("nodes", "file_paths", "JSON", False, "[]", "ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'"),
    ("provider_configs", "secret_env_key", "VARCHAR(128)", False, "", "ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''"),
    ("provider_configs", "revision", "INTEGER", True, "1", "ALTER TABLE provider_configs ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"),
    ("provider_configs", "secret_change_pending", "BOOLEAN", True, "0", "ALTER TABLE provider_configs ADD COLUMN secret_change_pending BOOLEAN NOT NULL DEFAULT 0"),
    ("provider_configs", "secret_change_claim", "VARCHAR(64)", False, None, "ALTER TABLE provider_configs ADD COLUMN secret_change_claim VARCHAR(64)"),
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
    ("agent_grants", "workspace_scope", "VARCHAR(20)", True, "legacy_project", "ALTER TABLE agent_grants ADD COLUMN workspace_scope VARCHAR(20) NOT NULL DEFAULT 'legacy_project'"),
    ("agent_grants", "mode", "VARCHAR(32)", False, None, "ALTER TABLE agent_grants ADD COLUMN mode VARCHAR(32)"),
)
INDEX_SQL = "CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type = 'child_of' AND is_mainline = 1"
WORKSPACE_GRANT_INDEX_SQL = "CREATE UNIQUE INDEX ux_agent_grants_one_active_workspace ON agent_grants((1)) WHERE workspace_scope = 'workspace' AND status = 'active' AND revoked_at IS NULL"
INDEXES = {
 "ux_edges_one_mainline_per_parent": INDEX_SQL,
 "ux_agent_grants_one_active_workspace": WORKSPACE_GRANT_INDEX_SQL,
}
PROVIDER_SELECTION_TABLE_SQL = """CREATE TABLE provider_selection (singleton_id INTEGER NOT NULL PRIMARY KEY, provider_id VARCHAR(36) REFERENCES provider_configs(id) ON DELETE SET NULL, selection_revision INTEGER NOT NULL DEFAULT 1, updated_at DATETIME NOT NULL, CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1), CONSTRAINT ck_provider_selection_revision_safe CHECK (selection_revision >= 1 AND selection_revision <= 9007199254740991))"""

TRIGGERS = {
"trg_edges_one_mainline_insert": """CREATE TRIGGER trg_edges_one_mainline_insert BEFORE INSERT ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1); END""",
"trg_edges_one_mainline_update": """CREATE TRIGGER trg_edges_one_mainline_update BEFORE UPDATE OF from_node_id, relation_type, is_mainline ON edges WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1 BEGIN SELECT RAISE(ABORT, 'duplicate mainline for parent') WHERE EXISTS (SELECT 1 FROM edges WHERE from_node_id = NEW.from_node_id AND relation_type = 'child_of' AND is_mainline = 1 AND id != OLD.id); END""",
"trg_edges_normalize_null_insert": """CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
"trg_edges_normalize_null_update": """CREATE TRIGGER trg_edges_normalize_null_update AFTER UPDATE OF weight, note ON edges WHEN NEW.weight IS NULL OR NEW.note IS NULL BEGIN UPDATE edges SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '') WHERE id = NEW.id; END""",
"trg_provider_revision_insert": """CREATE TRIGGER trg_provider_revision_insert BEFORE INSERT ON provider_configs WHEN typeof(NEW.revision) != 'integer' OR NEW.revision < 1 OR NEW.revision > 9007199254740991 BEGIN SELECT RAISE(ABORT, 'provider revision out of range'); END""",
"trg_provider_revision_update": """CREATE TRIGGER trg_provider_revision_update BEFORE UPDATE OF revision ON provider_configs WHEN typeof(NEW.revision) != 'integer' OR NEW.revision < 1 OR NEW.revision > 9007199254740991 BEGIN SELECT RAISE(ABORT, 'provider revision out of range'); END""",
}
OBJECT_SQL = {**INDEXES, **TRIGGERS}
# Canonical ownership makes optional-object applicability one shared policy.
# Objects owned by mandatory tables remain strict whenever schema validation runs.
OBJECT_OWNERS = {
    "ux_edges_one_mainline_per_parent": "edges",
    "ux_agent_grants_one_active_workspace": "agent_grants",
    "trg_edges_one_mainline_insert": "edges",
    "trg_edges_one_mainline_update": "edges",
    "trg_edges_normalize_null_insert": "edges",
    "trg_edges_normalize_null_update": "edges",
    "trg_provider_revision_insert": "provider_configs",
    "trg_provider_revision_update": "provider_configs",
}


def applicable_objects(existing_tables):
    """Return canonical objects whose owning table exists."""
    tables = set(existing_tables)
    return {name: sql for name, sql in OBJECT_SQL.items() if OBJECT_OWNERS[name] in tables}


def authority_critical_fk_violations(rows):
    """Classify SQLite foreign_key_check rows without exposing row identifiers."""
    return tuple(row for row in rows if len(row) >= 1 and row[0] == "provider_selection")

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
 "provider_configs": {"revision":_s("INTEGER",True,"1"),"secret_change_pending":_s(("INTEGER","NUMERIC"),True,"0"),"secret_change_claim":_s("TEXT") },
 "provider_selection": {"singleton_id":_s("INTEGER",True),"provider_id":_s("TEXT"),"selection_revision":_s("INTEGER",True,"1"),"updated_at":_s(("TEXT","NUMERIC"),True)},
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


def _executable_sql(sql):
    """Strip comments/literals while retaining quoted identifiers; reject incomplete SQL.

    This deliberately is not a SQL parser.  It only provides the small, fail-closed
    lexical boundary needed before searching sqlite_master DDL for required CHECKs.
    """
    source = sql or ""
    output = []
    i = 0
    while i < len(source):
        char = source[i]
        following = source[i + 1] if i + 1 < len(source) else ""
        if char == "-" and following == "-":
            i += 2
            while i < len(source) and source[i] not in "\r\n": i += 1
            output.append(" ")
            continue
        if char == "/" and following == "*":
            end = source.find("*/", i + 2)
            if end < 0: return None
            output.append(" ")
            i = end + 2
            continue
        if char == "'":
            i += 1
            while i < len(source):
                if source[i] == "'":
                    if i + 1 < len(source) and source[i + 1] == "'": i += 2; continue
                    i += 1
                    output.append(" ")
                    break
                i += 1
            else: return None
            continue
        if char in ('"', '`', '['):
            close = ']' if char == '[' else char
            i += 1
            identifier = []
            while i < len(source):
                if source[i] == close:
                    if i + 1 < len(source) and source[i + 1] == close:
                        identifier.append(close); i += 2; continue
                    i += 1
                    decoded_identifier = "".join(identifier)
                    # Quoted identifiers are emitted atomically only when their
                    # decoded value is exactly one ordinary identifier token.
                    # Otherwise delimiter contents could forge CHECK syntax.
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", decoded_identifier) is None:
                        return None
                    output.extend((" ", decoded_identifier, " "))
                    break
                identifier.append(source[i]); i += 1
            else: return None
            continue
        output.append(char)
        i += 1
    return "".join(output)


def provider_selection_contract_problem(table_info, foreign_keys, table_sql):
    """Return a structural incompatibility, independent of DDL formatting/order."""
    expected = {
        "singleton_id": ("INTEGER", True, None, 1),
        "provider_id": ("VARCHAR(36)", False, None, 0),
        "selection_revision": ("INTEGER", True, "1", 0),
        "updated_at": ("DATETIME", True, None, 0),
    }
    rows = {row[1]: row for row in table_info}
    if set(rows) != set(expected): return "columns"
    for name, (declared, not_null, default, pk) in expected.items():
        row = rows[name]
        if (str(row[2]).upper(), bool(row[3]), normalize_default(row[4]), int(row[5])) != (declared, not_null, default, pk):
            return f"column {name}"
    matching = [row for row in foreign_keys if row[2:8] == ("provider_configs", "provider_id", "id", "NO ACTION", "SET NULL", "NONE")]
    if len(matching) != 1 or len(foreign_keys) != 1: return "foreign key"
    executable = _executable_sql(table_sql)
    if executable is None: return "sql lexical"
    normalized = normalize_sql(executable)
    # Names make accidental replacement visible; predicates are checked only in
    # executable SQL, after comments/literals have been removed fail-closed.
    if not re.search(r"constraint\s+ck_provider_selection_singleton\s+check", normalized) or not re.search(r"check\(+\s*singleton_id\s*=\s*1\s*\)+", normalized):
        return "singleton check"
    if not re.search(r"constraint\s+ck_provider_selection_revision_safe\s+check", normalized):
        return "revision check"
    revision_between = re.search(r"check\(+\s*selection_revision\s+between\s+1\s+and\s+9007199254740991\s*\)+", normalized)
    revision_bounds = re.search(r"check\(+\s*selection_revision\s*>\s*=\s*1\s+and\s+selection_revision\s*<\s*=\s*9007199254740991\s*\)+", normalized)
    if not (revision_between or revision_bounds): return "revision check"
    return None
