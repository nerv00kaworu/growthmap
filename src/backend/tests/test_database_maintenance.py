import os, sqlite3
from pathlib import Path
import pytest
from desktop import database_maintenance as dm

def fixture(path):
 c=sqlite3.connect(path);c.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at TEXT,updated_at TEXT);CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT,summary TEXT,node_type TEXT,status TEXT,maturity TEXT);CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),from_node_id TEXT REFERENCES nodes(id),to_node_id TEXT REFERENCES nodes(id),relation_type TEXT);CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),block_type TEXT,content JSON,order_index INTEGER);CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),actor_type TEXT,action_type TEXT,created_at TEXT);CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER);""");c.execute("insert into projects values('p','x','','',NULL,'active','{}','','')");c.commit();c.close()

def test_durability_metadata_matches_platform_contract(tmp_path):
 p=tmp_path/'flush.bin';p.write_bytes(b'durability-evidence')
 result=dm._durability(p,p.parent)
 if os.name=='nt': assert result=={'fileFlush':'FlushFileBuffers','directoryFlush':'unsupported-windows-best-effort'}
 else: assert result=={'fileFsync':True,'directoryFsync':True}

def test_rejects_trigger_view_and_oversize(tmp_path,monkeypatch):
 for sql in ["CREATE VIEW evil AS SELECT * FROM projects","CREATE TRIGGER evil AFTER INSERT ON projects BEGIN SELECT 1; END"]:
  p=tmp_path/(str(abs(hash(sql)))+'.db');fixture(p);c=sqlite3.connect(p);c.execute(sql);c.close()
  with pytest.raises(ValueError,match='unapproved'):dm.validate(p)
 p=tmp_path/'large.db';fixture(p);monkeypatch.setattr(dm,'MAX_BYTES',100)
 with pytest.raises(ValueError,match='size'):dm.validate(p)

def test_accepts_canonical_edge_integrity_objects_only(tmp_path):
 p=tmp_path/'canonical.db';fixture(p);c=sqlite3.connect(p)
 c.execute("CREATE UNIQUE INDEX ux_edges_one_mainline_per_parent ON edges(from_node_id) WHERE relation_type='child_of'")
 c.execute("CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges BEGIN UPDATE edges SET relation_type=relation_type WHERE id=NEW.id; END")
 c.close();assert dm.validate(p)['valid'] is True
 p2=tmp_path/'lookalike.db';fixture(p2);c=sqlite3.connect(p2)
 c.execute("CREATE TRIGGER trg_edges_not_canonical AFTER INSERT ON edges BEGIN SELECT 1; END");c.close()
 with pytest.raises(ValueError,match='unapproved'):dm.validate(p2)

def test_accepts_exact_canonical_gameplay_extension_and_rejects_lookalikes(tmp_path):
 p=tmp_path/'abyss.db';fixture(p);c=sqlite3.connect(p)
 columns=dm.EXTENSION_TABLE_COLUMNS['schema_migrations']
 c.execute('''CREATE TABLE schema_migrations (
              migration_id TEXT PRIMARY KEY,
              checksum VARCHAR(64) NOT NULL,
              applied_at DATETIME NOT NULL
            )''')
 c.close();assert dm.validate(p)['valid'] is True
 p2=tmp_path/'wrong-columns.db';fixture(p2);c=sqlite3.connect(p2);c.execute('CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY,checksum TEXT,applied_at TEXT,secret TEXT)');c.close()
 with pytest.raises(ValueError,match='incompatible extension schema object'):dm.validate(p2)
 p3=tmp_path/'wrong-owner.db';fixture(p3);c=sqlite3.connect(p3);c.execute('CREATE INDEX idx_game_events_pack ON projects(name)');c.close()
 with pytest.raises(ValueError,match='incompatible extension schema object'):dm.validate(p3)
 p4=tmp_path/'forged-trigger.db';fixture(p4);c=sqlite3.connect(p4)
 c.execute('CREATE TABLE player_event_resolutions(id TEXT PRIMARY KEY,run_id TEXT,content_pack_id TEXT,event_id TEXT,choice_id TEXT,sequence_no INTEGER,idempotency_key TEXT,content_version TEXT,event_key TEXT,choice_key TEXT,known_state_json TEXT,input_refs_json TEXT,outcome_json TEXT,effects_json TEXT,outputs_json TEXT,resolved_at TEXT,integrity_hash TEXT)')
 c.execute('CREATE TRIGGER trg_resolution_immutable_delete BEFORE DELETE ON player_event_resolutions BEGIN SELECT 1; END');c.close()
 with pytest.raises(ValueError,match='incompatible extension schema object'):dm.validate(p4)

def test_legacy_canonical_schema_is_accepted_but_never_declared_current(tmp_path):
 p=tmp_path/'legacy.db';fixture(p);c=sqlite3.connect(p);c.execute('PRAGMA user_version=1');c.close()
 assert dm.validate(p)['valid'] is True
 status=dm.schema_status(p);assert status['migrationNeeded'] is True
 assert 'column:projects.revision' in status['reasons'] and 'column:nodes.revision' in status['reasons'] and 'user_version:1' in status['reasons']


def test_version_one_with_compatibility_surface_still_requires_version_advancement(tmp_path):
 p=tmp_path/'partial.db';fixture(p);c=sqlite3.connect(p)
 for table in ('projects','nodes','edges','content_blocks'):
  c.execute(f'ALTER TABLE {table} ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
 c.execute('CREATE TABLE branches(id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 1)')
 c.execute("ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36)");c.execute("ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'");c.execute("ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'");c.execute("ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''")
 c.execute("ALTER TABLE edges ADD COLUMN is_mainline BOOLEAN DEFAULT 0");c.execute("ALTER TABLE edges ADD COLUMN weight FLOAT DEFAULT 1.0");c.execute("ALTER TABLE edges ADD COLUMN note TEXT DEFAULT ''")
 for sql in (__import__('db.migrations',fromlist=['INDEX_SQL']).INDEX_SQL,*__import__('db.migrations',fromlist=['TRIGGERS']).TRIGGERS.values()):c.execute(sql)
 c.execute('PRAGMA user_version=1');c.close()
 status=dm.schema_status(p);assert status['migrationNeeded'] is True and 'user_version:1' in status['reasons']


def _make_current(path):
 c=sqlite3.connect(path);c.execute('CREATE TABLE IF NOT EXISTS branches(id TEXT PRIMARY KEY)')
 for spec in __import__('db.schema_contract',fromlist=['COLUMNS']).COLUMNS:
  if spec[1] not in {row[1] for row in c.execute(f'pragma table_info({spec[0]})')}:c.execute(spec[5])
 contract=__import__('db.schema_contract',fromlist=['ORM_READ_COLUMNS'])
 for table,columns in contract.ORM_READ_COLUMNS.items():
  present={row[1] for row in c.execute(f'pragma table_info({table})')}
  for name,expected in columns.items():
   if name not in present:c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {expected if isinstance(expected,str) else expected[0]}')
 for sql in ("ALTER TABLE edges ADD COLUMN is_mainline BOOLEAN DEFAULT 0","ALTER TABLE edges ADD COLUMN weight FLOAT DEFAULT 1","ALTER TABLE edges ADD COLUMN note TEXT DEFAULT ''"):
  try:c.execute(sql)
  except sqlite3.OperationalError as error:
   if 'duplicate column' not in str(error):raise
 contract=__import__('db.schema_contract',fromlist=['OBJECT_SQL'])
 for sql in contract.OBJECT_SQL.values():
  try:c.execute(sql)
  except sqlite3.OperationalError as error:
   if 'already exists' not in str(error):raise
 c.execute(f'pragma user_version={contract.CURRENT_USER_VERSION}');c.close()

@pytest.mark.parametrize('ddl,reason',[
 ("ALTER TABLE projects RENAME TO old_projects; CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,description TEXT,goal TEXT,root_node_id TEXT,status TEXT,settings JSON,created_at TEXT,updated_at TEXT,revision TEXT NOT NULL DEFAULT 1); INSERT INTO projects SELECT id,name,description,goal,root_node_id,status,settings,created_at,updated_at,COALESCE(revision,1) FROM old_projects; DROP TABLE old_projects","incompatible_column:projects.revision"),
 ("DROP TRIGGER trg_edges_normalize_null_insert; CREATE TRIGGER trg_edges_normalize_null_insert AFTER INSERT ON edges BEGIN SELECT 1; END","incompatible_object:trg_edges_normalize_null_insert"),
 ("DROP INDEX ux_edges_one_mainline_per_parent; CREATE INDEX ux_edges_one_mainline_per_parent ON edges(to_node_id)","incompatible_object:ux_edges_one_mainline_per_parent"),
])
def test_forged_v2_compatibility_surface_never_reports_current(tmp_path,ddl,reason):
 p=tmp_path/'forged.db';fixture(p);_make_current(p);c=sqlite3.connect(p);c.executescript(ddl);c.close()
 status=dm.schema_status(p);assert status['migrationNeeded'] is True and reason in status['reasons']


@pytest.mark.parametrize('table,column,ddl',[
 ('projects','settings','ALTER TABLE projects DROP COLUMN settings'),
 ('nodes','priority','ALTER TABLE nodes DROP COLUMN priority'),
 ('edges','created_at','ALTER TABLE edges DROP COLUMN created_at'),
 ('content_blocks','created_by','ALTER TABLE content_blocks DROP COLUMN created_by'),
])
def test_v2_missing_orm_mapped_column_is_never_current(tmp_path,table,column,ddl):
 p=tmp_path/'missing.db';fixture(p);_make_current(p)
 c=sqlite3.connect(p);c.execute(ddl);c.close()
 status=dm.schema_status(p);assert status['migrationNeeded'] is True and f'missing_orm_column:{table}.{column}' in status['reasons']


def test_exact_v2_is_current_and_newer_version_fails_closed(tmp_path):
 p=tmp_path/'current.db';fixture(p);_make_current(p);assert dm.schema_status(p)['migrationNeeded'] is False
 c=sqlite3.connect(p);c.execute('pragma user_version=3');c.close()
 with pytest.raises(ValueError,match='newer'):dm.schema_status(p)


def test_installed_canonical_abyss_database_contract_when_supplied():
 fixture_path=os.getenv('GROWTHMAP_CANONICAL_ABYSS_DB')
 if not fixture_path: pytest.skip('canonical Abyss database fixture not supplied')
 meta=dm.validate(Path(fixture_path));assert meta['valid'] is True;assert meta['counts']['projects']>=1

def test_validated_snapshot_rejects_hardlink_and_uses_combined_validation(tmp_path):
 p=tmp_path/'a.db';fixture(p);hard=tmp_path/'hard.db';os.link(p,hard)
 with pytest.raises(ValueError,match='single-link'):dm.validated_snapshot(hard,tmp_path/'out.db')
