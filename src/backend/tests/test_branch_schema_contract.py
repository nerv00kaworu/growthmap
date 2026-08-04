import asyncio, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.database import Base
from db.migrations import migrate_sqlite
from db.schema_contract import ORM_READ_COLUMNS
from desktop import database_maintenance as dm
from models.models import Branch
from models.schemas import BranchOut

FIXTURE = Path(__file__).parents[3] / "desktop/scripts/create-e2e-fixture.py"
BRANCH_FIELDS = {"id", "project_id", "name", "description", "source_node_id", "status", "created_at", "revision"}


def fixture(tmp_path):
    path = tmp_path / "fixture-branch.sqlite"
    subprocess.run([sys.executable, str(FIXTURE), str(path)], check=True)
    return path


def test_branch_contract_is_complete_for_mapped_and_response_fields():
    assert set(Branch.__table__.columns.keys()) == BRANCH_FIELDS
    assert set(ORM_READ_COLUMNS["branches"]) == BRANCH_FIELDS
    assert BRANCH_FIELDS == set(BranchOut.model_fields)


@pytest.mark.parametrize("version", [1, 2])
def test_incomplete_branch_table_rejected_before_acceptance(tmp_path, version):
    path = fixture(tmp_path)
    connection = sqlite3.connect(path)
    connection.execute("ALTER TABLE branches DROP COLUMN status")
    connection.execute(f"PRAGMA user_version={version}")
    connection.close()
    status = dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"]
    assert "missing_orm_column:branches.status" in status["reasons"]

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        with pytest.raises(RuntimeError, match="missing ORM read column branches.status"):
            async with engine.begin() as connection:
                await migrate_sqlite(connection)
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("PRAGMA user_version")).scalar() == version
        await engine.dispose()
    asyncio.run(run())


def test_branch_orm_read_and_response_serialization(tmp_path):
    path = tmp_path / "branch-orm.db"
    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await migrate_sqlite(connection)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        stamp = datetime(2026, 8, 3, tzinfo=timezone.utc)
        async with factory() as session:
            branch = Branch(id="branch", project_id="project", name="Branch", description="kept", source_node_id=None, status="active", created_at=stamp)
            session.add(branch); await session.commit()
        async with factory() as session:
            loaded = await session.get(Branch, "branch")
            output = BranchOut.model_validate(loaded).model_dump(mode="json")
        await engine.dispose()
        assert output == {"id":"branch","project_id":"project","name":"Branch","description":"kept","source_node_id":None,"status":"active","created_at":"2026-08-03T00:00:00","revision":1}
    asyncio.run(run())


@pytest.mark.parametrize("version", [1, 2])
def test_expected_legacy_branch_schema_upgrades_idempotently_and_preserves_data(tmp_path, version):
    path = fixture(tmp_path)
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO branches(id,project_id,name,description,source_node_id,status,created_at,revision) VALUES('b','fixture','legacy','kept','root','active','2026-08-03T00:00:00+00:00',7)")
    if version == 1:
        connection.execute("ALTER TABLE branches DROP COLUMN revision")
    connection.execute(f"PRAGMA user_version={version}")
    connection.commit(); connection.close()

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection: await migrate_sqlite(connection)
        async with engine.begin() as connection: await migrate_sqlite(connection)
        async with engine.connect() as connection:
            row = (await connection.exec_driver_sql("SELECT id,project_id,name,description,source_node_id,status,created_at,revision FROM branches WHERE id='b'")).one()
            assert tuple(row) == ("b","fixture","legacy","kept","root","active","2026-08-03T00:00:00+00:00",1 if version == 1 else 7)
            assert (await connection.exec_driver_sql("PRAGMA user_version")).scalar() == 2
        await engine.dispose()
    asyncio.run(run())


def test_branch_created_at_null_fails_closed(tmp_path):
    path = fixture(tmp_path)
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO branches(id,project_id,name,created_at,revision) VALUES('b','fixture','bad',NULL,1)")
    connection.commit(); connection.close()
    status = dm.schema_status(path)
    assert "null_data:branches.created_at" in status["reasons"]


def test_historical_nullable_branch_response_fields_fail_if_stored_null(tmp_path):
    path = fixture(tmp_path)
    connection = sqlite3.connect(path)
    connection.executescript("ALTER TABLE branches RENAME TO old_branches; CREATE TABLE branches(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,description TEXT,source_node_id TEXT,status TEXT,created_at DATETIME,revision INTEGER NOT NULL DEFAULT 1); DROP TABLE old_branches;")
    connection.execute("INSERT INTO branches(id,project_id,name,description,status,created_at,revision) VALUES('b',NULL,NULL,NULL,NULL,'2026-08-03',1)")
    connection.commit(); connection.close()
    reasons = dm.schema_status(path)["reasons"]
    for column in ("project_id", "name", "description", "status"):
        assert f"null_data:branches.{column}" in reasons
