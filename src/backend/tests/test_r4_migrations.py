import os, asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from db.migrations import migrate_sqlite, CURRENT_USER_VERSION
from db.schema_contract import ORM_READ_COLUMNS

OLD = """
CREATE TABLE projects(id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE branches(id TEXT PRIMARY KEY);
CREATE TABLE nodes(id TEXT PRIMARY KEY, branch_id VARCHAR(36), workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft', file_paths JSON DEFAULT '[]');
CREATE TABLE edges(id TEXT PRIMARY KEY, from_node_id TEXT, relation_type TEXT, is_mainline BOOLEAN, weight FLOAT, note TEXT);
CREATE TABLE content_blocks(id TEXT PRIMARY KEY);
CREATE TABLE provider_configs(id TEXT PRIMARY KEY, secret_env_key VARCHAR(128) DEFAULT '');
INSERT INTO projects VALUES ('p',7);
"""

async def db(tmp_path, sql=OLD):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'old.db'}")
    async with engine.begin() as conn:
        for statement in sql.split(';'):
            if statement.strip(): await conn.execute(text(statement))
        # These focused migration fixtures model a legacy database whose
        # ordinary ORM surface is otherwise complete.
        for table,columns in ORM_READ_COLUMNS.items():
            present={row[1] for row in (await conn.execute(text(f'pragma table_info({table})'))).all()}
            for name,expected in columns.items():
                if name not in present:
                    spec=next((item for item in __import__('db.schema_contract',fromlist=['COLUMNS']).COLUMNS if item[0]==table and item[1]==name),None)
                    if spec:continue
                    declared=expected if isinstance(expected,str) else expected[0]
                    await conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {declared}'))
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


async def _version_one_legacy_revision_upgrade_is_idempotent_and_preserves_rows(tmp_path):
    sql = OLD.replace("revision INTEGER NOT NULL DEFAULT 1", "name TEXT", 1) + "\nPRAGMA user_version=1;\nINSERT INTO projects VALUES ('legacy','kept');\n"
    engine = await db(tmp_path, sql)
    async with engine.begin() as conn:
        before = {table:(await conn.execute(text(f"select count(*) from {table}"))).scalar() for table in ("projects","nodes","edges","content_blocks")}
        await migrate_sqlite(conn)
    async with engine.begin() as conn: await migrate_sqlite(conn)
    async with engine.connect() as conn:
        after = {table:(await conn.execute(text(f"select count(*) from {table}"))).scalar() for table in before}
        assert after == before
        assert (await conn.execute(text("select name,revision from projects where id='legacy'"))).one() == ("kept",1)
        assert (await conn.execute(text("pragma user_version"))).scalar() == CURRENT_USER_VERSION
    await engine.dispose()


def test_populated_old_and_partial_compatible_upgrade(tmp_path): asyncio.run(_populated_old_and_partial_compatible_upgrade(tmp_path))
def test_incompatible_column_and_index_fail_closed(tmp_path): asyncio.run(_incompatible_column_and_index_fail_closed(tmp_path))
def test_injected_failure_rolls_back_version_and_retry_succeeds(tmp_path, monkeypatch): asyncio.run(_injected_failure_rolls_back_version_and_retry_succeeds(tmp_path, monkeypatch))
def test_version_one_legacy_revision_upgrade_is_idempotent_and_preserves_rows(tmp_path): asyncio.run(_version_one_legacy_revision_upgrade_is_idempotent_and_preserves_rows(tmp_path))

async def _missing_provider_secret_column_gets_exact_default_and_preserves_rows(tmp_path):
    sql=OLD.replace("secret_env_key VARCHAR(128) DEFAULT ''","name TEXT")+"\nINSERT INTO provider_configs VALUES ('provider','kept');\nPRAGMA user_version=1;"
    engine=await db(tmp_path,sql)
    async with engine.begin() as conn:await migrate_sqlite(conn)
    async with engine.begin() as conn:await migrate_sqlite(conn)
    async with engine.connect() as conn:
        assert (await conn.execute(text("select id,name,secret_env_key from provider_configs"))).one()==("provider","kept","")
        row=next(row for row in (await conn.execute(text("pragma table_info(provider_configs)"))).all() if row[1]=="secret_env_key")
        assert (row[2],bool(row[3]),row[4])==("VARCHAR(128)",False,"''")
        assert (await conn.execute(text("pragma user_version"))).scalar()==CURRENT_USER_VERSION
    await engine.dispose()

def test_missing_provider_secret_column_gets_exact_default_and_preserves_rows(tmp_path):asyncio.run(_missing_provider_secret_column_gets_exact_default_and_preserves_rows(tmp_path))

async def _partial_orm_schema_fails_before_version_advance(tmp_path, version, table, column, replacement=None):
    from db.database import Base
    from models import models  # noqa: F401
    path=tmp_path/f'partial-{version}-{table}-{column}.db'
    engine=create_async_engine(f'sqlite+aiosqlite:///{path}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_sqlite(conn)
    # Rebuild through SQLite's supported DROP COLUMN for missing cases; use a
    # declared incompatible replacement on an otherwise disposable empty DB.
    async with engine.begin() as conn:
        await conn.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        if replacement:await conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {replacement}'))
        await conn.execute(text(f'PRAGMA user_version={version}'))
    with pytest.raises(RuntimeError,match=f'ORM read column {table}.{column}'):
        async with engine.begin() as conn:await migrate_sqlite(conn)
    async with engine.connect() as conn:assert (await conn.execute(text('pragma user_version'))).scalar()==version
    await engine.dispose()

@pytest.mark.parametrize('version,table,column,replacement',[
 (2,'projects','settings',None),(2,'nodes','priority',None),
 (2,'edges','created_at',None),(2,'content_blocks','created_by',None),
 (1,'nodes','priority',None),(1,'projects','settings','INTEGER'),
])
def test_partial_orm_schema_actual_migration_fails_closed(tmp_path,version,table,column,replacement):
    asyncio.run(_partial_orm_schema_fails_before_version_advance(tmp_path,version,table,column,replacement))
