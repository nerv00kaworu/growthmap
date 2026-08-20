"""Focused product integration in an isolated subprocess per test.

The subprocess boundary makes db.database's import-time engine deterministic and
proves every engine points at the pytest-owned absolute temporary path.
"""
import os, subprocess, sys, textwrap
from pathlib import Path
import pytest

BACKEND=Path(__file__).parents[1]
SENTINELS={
    (BACKEND/"growthmap.db").resolve(),
    Path("/mnt/c/Users/nerv0/AppData/Roaming/growthmap-desktop/growthmap.db").resolve(),
}

@pytest.fixture
def product_case(tmp_path):
    database=(tmp_path/"authority.db").resolve()
    assert database not in SENTINELS and database.parent==tmp_path.resolve()
    def run(body, **extra):
        env=os.environ.copy(); env.update({"PYTHONPATH":str(BACKEND),"APP_ENV":"test","DATABASE_URL":f"sqlite+aiosqlite:///{database}",**extra})
        script=textwrap.dedent(f"""
        import asyncio
        from pathlib import Path
        from sqlalchemy import text
        from db.database import Base,engine
        import models.models
        from db.migrations import migrate_sqlite
        assert Path(engine.url.database).resolve()==Path({str(database)!r})
        async def case():
            {textwrap.indent(textwrap.dedent(body),'    ').lstrip()}
        asyncio.run(case())
        """)
        return subprocess.run([sys.executable,"-c",script],cwd=BACKEND,env=env,text=True,capture_output=True)
    return database,run

def test_fresh_create_all_migrate_reopen_same_structural_contract(product_case):
    database,run=product_case
    result=run("""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_sqlite(conn)
    await engine.dispose()
    from sqlalchemy.ext.asyncio import create_async_engine
    reopened=create_async_engine(str(engine.url))
    async with reopened.begin() as conn:
        await migrate_sqlite(conn)
        assert (await conn.execute(text('SELECT singleton_id,provider_id,selection_revision FROM provider_selection'))).one()==(1,None,1)
    await reopened.dispose()
    """)
    assert result.returncode==0,result.stderr

def test_create_all_v11_upgrade_seeds_only_empty_selection_authority(product_case):
    database,run=product_case
    result=run("""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('PRAGMA user_version=11'))
        assert not (await conn.execute(text('SELECT 1 FROM provider_selection'))).first()
        await migrate_sqlite(conn)
        assert (await conn.execute(text('SELECT singleton_id,provider_id,selection_revision FROM provider_selection'))).one()==(1,None,1)
        assert (await conn.execute(text('PRAGMA user_version'))).scalar()==12
    """)
    assert result.returncode==0,result.stderr

def test_missing_singleton_fails_closed_without_repair(product_case):
    database,run=product_case
    result=run("""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('PRAGMA user_version=12'))
    try:
        async with engine.begin() as conn: await migrate_sqlite(conn)
    except RuntimeError as exc: assert 'singleton' in str(exc)
    else: raise AssertionError('missing singleton accepted')
    """)
    assert result.returncode==0,result.stderr

def test_nonempty_pre_v12_selection_container_fails_closed(product_case):
    database,run=product_case
    result=run("""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('DROP TABLE provider_selection'))
        await conn.execute(text('CREATE TABLE provider_selection(singleton_id INTEGER PRIMARY KEY,provider_id VARCHAR(36),selection_revision INTEGER NOT NULL DEFAULT 1,updated_at DATETIME NOT NULL)'))
        await conn.execute(text("INSERT INTO provider_selection VALUES(2,NULL,2,CURRENT_TIMESTAMP)"))
        await conn.execute(text('PRAGMA user_version=11'))
    try:
        async with engine.begin() as conn: await migrate_sqlite(conn)
    except Exception as exc: assert 'provider_selection' in str(exc) or 'CHECK constraint' in str(exc)
    else: raise AssertionError('malformed pre-v12 authority accepted')
    """)
    assert result.returncode==0,result.stderr

def test_injected_v12_migration_rolls_back(product_case):
    database,run=product_case
    result=run("""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text('DROP TABLE provider_selection'))
        await conn.execute(text('PRAGMA user_version=11'))
    try:
        async with engine.begin() as conn: await migrate_sqlite(conn)
    except RuntimeError: pass
    else: raise AssertionError('injection did not fail')
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM sqlite_schema WHERE name='provider_selection'"))).scalar()==0
        assert (await conn.execute(text('PRAGMA user_version'))).scalar()==11
    """,GROWTHMAP_TEST_FAIL_MIGRATION_PHASE="provider_selection_v12")
    assert result.returncode==0,result.stderr
