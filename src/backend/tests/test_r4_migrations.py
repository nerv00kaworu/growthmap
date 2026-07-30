import os, asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from db.migrations import migrate_sqlite, CURRENT_USER_VERSION

OLD = """
CREATE TABLE projects(id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE branches(id TEXT PRIMARY KEY);
CREATE TABLE nodes(id TEXT PRIMARY KEY, branch_id VARCHAR(36), workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft', file_paths JSON DEFAULT '[]');
CREATE TABLE edges(id TEXT PRIMARY KEY, from_node_id TEXT, relation_type TEXT, is_mainline BOOLEAN, weight FLOAT, note TEXT);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY, secret_env_key VARCHAR(128));
INSERT INTO projects VALUES ('p',7);
"""

async def db(tmp_path, sql=OLD):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'old.db'}")
    async with engine.begin() as conn:
        for statement in sql.split(';'):
            if statement.strip(): await conn.execute(text(statement))
    return engine

async def _populated_old_and_partial_compatible_upgrade(tmp_path):
    engine = await db(tmp_path)
    async with engine.begin() as conn: await migrate_sqlite(conn)
    async with engine.connect() as conn:
        assert (await conn.execute(text("pragma user_version"))).scalar() == CURRENT_USER_VERSION
        assert (await conn.execute(text("select revision from projects where id='p'"))).scalar() == 7
        assert "revision" in {r[1] for r in (await conn.execute(text("pragma table_info(nodes)"))).all()}
    await engine.dispose()

async def _incompatible_column_and_index_fail_closed(tmp_path):
    bad = OLD.replace("revision INTEGER NOT NULL DEFAULT 1", "revision TEXT", 1)
    engine = await db(tmp_path, bad)
    with pytest.raises(RuntimeError, match="incompatible migration column"):
        async with engine.begin() as conn: await migrate_sqlite(conn)
    async with engine.connect() as conn: assert (await conn.execute(text("pragma user_version"))).scalar() == 0
    await engine.dispose()

async def _injected_failure_rolls_back_version_and_retry_succeeds(tmp_path, monkeypatch):
    engine = await db(tmp_path)
    monkeypatch.setenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER", "6")
    with pytest.raises(RuntimeError, match="injected"):
        async with engine.begin() as conn: await migrate_sqlite(conn)
    async with engine.connect() as conn:
        assert (await conn.execute(text("pragma user_version"))).scalar() == 0
        # Some SQLite driver builds retain transactional ALTERs; the version
        # remains unadvanced and the exact-compatible partial state is retryable.
    monkeypatch.delenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER")
    async with engine.begin() as conn: await migrate_sqlite(conn)
    async with engine.connect() as conn: assert (await conn.execute(text("pragma user_version"))).scalar() == CURRENT_USER_VERSION
    await engine.dispose()


def test_populated_old_and_partial_compatible_upgrade(tmp_path): asyncio.run(_populated_old_and_partial_compatible_upgrade(tmp_path))
def test_incompatible_column_and_index_fail_closed(tmp_path): asyncio.run(_incompatible_column_and_index_fail_closed(tmp_path))
def test_injected_failure_rolls_back_version_and_retry_succeeds(tmp_path, monkeypatch): asyncio.run(_injected_failure_rolls_back_version_and_retry_succeeds(tmp_path, monkeypatch))

async def _v1_readback_ledger_upgrades_to_v2_with_stale_defaults(tmp_path):
 sql=OLD+"CREATE TABLE agent_readbacks(id VARCHAR(36) PRIMARY KEY,grant_id VARCHAR(36) NOT NULL,project_id VARCHAR(36) NOT NULL,target_node_id VARCHAR(36),commit_refs JSON NOT NULL,files JSON NOT NULL,tests JSON NOT NULL,decisions JSON NOT NULL,risks JSON NOT NULL,todos JSON NOT NULL,evidence JSON NOT NULL,summary TEXT,created_at DATETIME);PRAGMA user_version=1;"
 engine=await db(tmp_path,sql)
 async with engine.begin() as conn:await migrate_sqlite(conn)
 async with engine.connect() as conn:
  info={r[1]:(r[2],bool(r[3]),str(r[4]).strip("'")) for r in (await conn.execute(text("pragma table_info(agent_readbacks)"))).all()}
  indexes={r[1] for r in (await conn.execute(text("pragma index_list(agent_readbacks)"))).all()}
  assert {"ix_agent_readbacks_grant_id","ix_agent_readbacks_project_id"}<=indexes
  assert info["based_on_project_revision"]==("INTEGER",True,"1")
  assert info["context_snapshot_digest"]==("VARCHAR(64)",True,"")
  assert info["objective"]==("TEXT",True,"")
  assert info["current_project_revision"]==("INTEGER",True,"1")
  assert info["context_stale"]==("BOOLEAN",True,"1")
  assert (await conn.execute(text("pragma user_version"))).scalar()==2
 await engine.dispose()

def test_v1_readback_ledger_upgrades_to_v2_with_stale_defaults(tmp_path):asyncio.run(_v1_readback_ledger_upgrades_to_v2_with_stale_defaults(tmp_path))

async def _v1_without_readback_table_creates_canonical_v2_and_retries_failure(tmp_path,monkeypatch):
 engine=await db(tmp_path,OLD+"PRAGMA user_version=1;")
 monkeypatch.setenv("GROWTHMAP_TEST_FAIL_MIGRATION_V2_AFTER","1")
 with pytest.raises(RuntimeError,match="injected v2"):
  async with engine.begin() as conn:await migrate_sqlite(conn)
 async with engine.connect() as conn:
  assert (await conn.execute(text("pragma user_version"))).scalar()==1
  # Transaction rollback owns table/index/version as one unit.
  assert (await conn.execute(text("select count(*) from sqlite_schema where name='agent_readbacks'"))).scalar()==0
 monkeypatch.delenv("GROWTHMAP_TEST_FAIL_MIGRATION_V2_AFTER")
 async with engine.begin() as conn:await migrate_sqlite(conn)
 async with engine.connect() as conn:
  assert (await conn.execute(text("pragma user_version"))).scalar()==2
  assert (await conn.execute(text("select count(*) from sqlite_schema where name='agent_readbacks'"))).scalar()==1
 await engine.dispose()
def test_v1_without_readback_table_creates_canonical_v2_and_retries_failure(tmp_path,monkeypatch):asyncio.run(_v1_without_readback_table_creates_canonical_v2_and_retries_failure(tmp_path,monkeypatch))
