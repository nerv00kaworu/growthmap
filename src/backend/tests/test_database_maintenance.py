import os, sqlite3, asyncio
from pathlib import Path
import pytest
from desktop import database_maintenance as dm

def fixture(path):
 c=sqlite3.connect(path);c.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT,created_at TEXT,updated_at TEXT);CREATE TABLE nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT,node_type TEXT,status TEXT,maturity TEXT);CREATE TABLE edges(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),from_node_id TEXT REFERENCES nodes(id),to_node_id TEXT REFERENCES nodes(id),relation_type TEXT);CREATE TABLE content_blocks(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),block_type TEXT,content TEXT,order_index INTEGER);CREATE TABLE action_logs(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),actor_type TEXT,action_type TEXT,created_at TEXT);CREATE TABLE provider_configs(id TEXT PRIMARY KEY,name TEXT,provider_type TEXT,model_name TEXT,enabled INTEGER);""");c.execute("insert into projects values('p','x','active','','')");c.commit();c.close()

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

def test_v2_schema_status_validates_readback_provenance_and_fails_closed(tmp_path):
 from sqlalchemy.ext.asyncio import create_async_engine
 from db.database import Base
 import models.models  # register canonical metadata
 from db.migrations import migrate_sqlite
 async def create(path):
  engine=create_async_engine(f"sqlite+aiosqlite:///{path}")
  async with engine.begin() as connection:
   await connection.run_sync(Base.metadata.create_all);await migrate_sqlite(connection)
  await engine.dispose()
 p=tmp_path/'v2.db';asyncio.run(create(p));assert dm.validate(p)['userVersion']==2;status=dm.schema_status(p);assert status['migrationNeeded'] is False,status
 c=sqlite3.connect(p);c.execute('PRAGMA writable_schema=ON');sql=c.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='agent_readbacks'").fetchone()[0];c.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name='agent_readbacks'",(sql.replace("\n\tobjective TEXT DEFAULT '' NOT NULL, ",""),));c.execute('PRAGMA writable_schema=OFF');c.commit();c.close()
 with pytest.raises(ValueError,match='agent_readbacks'):dm.validate(p)

def test_v2_readback_defaults_types_and_nullability_fail_closed(tmp_path):
 import subprocess,sys
 creator=Path(__file__).parents[3]/'desktop/scripts/create-e2e-fixture.py'
 for column,replacement in [('based_on_project_revision','DEFAULT 2'),('context_snapshot_digest',"DEFAULT 'wrong'"),('objective',"DEFAULT 'wrong'"),('current_project_revision','DEFAULT 2'),('context_stale','DEFAULT 0')]:
  p=tmp_path/f'fixture-{column}.db';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);sql=c.execute("select sql from sqlite_schema where name='agent_readbacks'").fetchone()[0];needle={r[1]:str(r[4]) for r in c.execute('pragma table_info(agent_readbacks)')}[column];c.execute('pragma writable_schema=on');c.execute("update sqlite_schema set sql=? where name='agent_readbacks'",(sql.replace(f'DEFAULT {needle}',replacement,1),));c.execute('pragma writable_schema=off');c.commit();c.close()
  with pytest.raises(ValueError,match='agent_readbacks'):dm.validate(p)
 p=tmp_path/'fixture-expression.db';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);sql=c.execute("select sql from sqlite_schema where name='agent_readbacks'").fetchone()[0];c.execute('pragma writable_schema=on');c.execute("update sqlite_schema set sql=? where name='agent_readbacks'",(sql.replace("objective TEXT NOT NULL DEFAULT ''","objective TEXT NOT NULL DEFAULT (lower(''))"),));c.execute('pragma writable_schema=off');c.commit();c.close()
 with pytest.raises(ValueError,match='nonliteral'):dm.validate(p)

def test_rejects_cross_project_edge_even_when_foreign_keys_are_satisfied(tmp_path):
 p=tmp_path/'cross.db';fixture(p);c=sqlite3.connect(p);c.execute("insert into projects values('q','q','active','','')");c.executemany("insert into nodes values(?,?,?,?,?,?)",[('a','p','a','idea','active','seed'),('b','q','b','idea','active','seed')]);c.execute("insert into edges values('e','p','a','b','child_of')");c.commit();c.close()
 with pytest.raises(ValueError,match='crosses project'):dm.validate(p)

def test_validated_snapshot_rejects_hardlink_and_uses_combined_validation(tmp_path):
 p=tmp_path/'a.db';fixture(p);hard=tmp_path/'hard.db';os.link(p,hard)
 with pytest.raises(ValueError,match='single-link'):dm.validated_snapshot(hard,tmp_path/'out.db')

def test_readback_index_and_fk_contract_fail_closed(tmp_path):
 import subprocess,sys
 creator=Path(__file__).parents[3]/'desktop/scripts/create-e2e-fixture.py'
 variants=["CREATE UNIQUE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id)","CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id) WHERE grant_id!=''","CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id,project_id)","CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(lower(grant_id))"]
 for i,sql in enumerate(variants):
  p=tmp_path/f'fixture-index-{i}.db';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);c.execute('drop index ix_agent_readbacks_grant_id');c.execute(sql);c.commit();c.close()
  with pytest.raises(ValueError,match='contract'):dm.validate(p)
 for i,(old,new) in enumerate([('ON DELETE SET NULL','ON DELETE CASCADE'),('REFERENCES nodes(id) ON DELETE SET NULL','')]):
  p=tmp_path/f'fixture-fk-{i}.db';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);sql=c.execute("select sql from sqlite_schema where name='agent_readbacks'").fetchone()[0];assert old in sql;c.execute('pragma writable_schema=on');c.execute("update sqlite_schema set sql=? where name='agent_readbacks'",(sql.replace(old,new,1),));c.execute('pragma writable_schema=off');c.commit();c.close()
  with pytest.raises(ValueError,match='contract'):dm.validate(p)


@pytest.mark.parametrize("definition",["id VARCHAR(36) NOT NULL, grant_id VARCHAR(36) NOT NULL","id VARCHAR(36) NOT NULL, grant_id VARCHAR(36) NOT NULL PRIMARY KEY"])
def test_v2_primary_key_attacks_fail_closed(tmp_path,definition):
 import subprocess,sys
 p=tmp_path/f'fixture-pk-{abs(hash(definition))}.db';creator=Path(__file__).parents[3]/'desktop/scripts/create-e2e-fixture.py';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);c.execute('alter table agent_readbacks rename to old_readbacks');c.execute(f"CREATE TABLE agent_readbacks({definition},project_id VARCHAR(36) NOT NULL,target_node_id VARCHAR(36),based_on_project_revision INTEGER NOT NULL DEFAULT '1',context_snapshot_digest VARCHAR(64) NOT NULL DEFAULT '',objective TEXT NOT NULL DEFAULT '',current_project_revision INTEGER NOT NULL DEFAULT '1',context_stale BOOLEAN NOT NULL DEFAULT '1',commit_refs JSON NOT NULL,files JSON NOT NULL,tests JSON NOT NULL,decisions JSON NOT NULL,risks JSON NOT NULL,todos JSON NOT NULL,evidence JSON NOT NULL,summary TEXT,created_at DATETIME)");c.execute('drop table old_readbacks');c.commit();c.close()
 with pytest.raises(ValueError,match='contract'):dm.validate(p)

@pytest.mark.parametrize('sql',["CREATE UNIQUE INDEX ux_attack ON agent_readbacks(grant_id)","CREATE INDEX ix_attack ON agent_readbacks(summary)"])
def test_v2_extra_indexes_fail_closed(tmp_path,sql):
 import subprocess,sys
 p=tmp_path/f'fixture-extra-{abs(hash(sql))}.db';creator=Path(__file__).parents[3]/'desktop/scripts/create-e2e-fixture.py';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);c.execute(sql);c.commit();c.close()
 with pytest.raises(ValueError,match='contract|unapproved'):dm.validate(p)

@pytest.mark.parametrize('sql',["CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id DESC)","CREATE INDEX ix_agent_readbacks_grant_id ON agent_readbacks(grant_id COLLATE NOCASE)"])
def test_v2_index_sort_and_collation_drift_fail_closed(tmp_path,sql):
 import subprocess,sys
 p=tmp_path/f'fixture-index-sem-{abs(hash(sql))}.db';creator=Path(__file__).parents[3]/'desktop/scripts/create-e2e-fixture.py';subprocess.run([sys.executable,str(creator),str(p)],check=True);c=sqlite3.connect(p);c.execute('drop index ix_agent_readbacks_grant_id');c.execute(sql);c.commit();c.close()
 with pytest.raises(ValueError):dm.validate(p)
