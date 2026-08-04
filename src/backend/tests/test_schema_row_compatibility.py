import asyncio, sqlite3, subprocess, sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.migrations import migrate_sqlite
from db.database import Base
from desktop import database_maintenance as dm
from models.models import Project, Node, Edge, ContentBlock
from models.schemas import ProjectOut, NodeOut, EdgeOut, ContentBlockOut

FIXTURE = Path(__file__).parents[3] / "desktop/scripts/create-e2e-fixture.py"
TIMESTAMPS = {
    "projects": ("created_at", "updated_at"),
    "nodes": ("created_at", "updated_at"),
    "edges": ("created_at",),
    "content_blocks": ("created_at", "updated_at"),
}
LEGITIMATE_NULLS = {
    "projects": ("description", "goal", "settings"),
    "nodes": (
        "summary", "priority", "confidence", "description", "rules_text",
        "constraints_text", "examples_text", "questions_text", "decision_notes",
        "tags", "file_paths", "created_by", "last_edited_by", "position_x", "position_y",
    ),
    "edges": ("weight", "note"),
    "content_blocks": ("created_by",),
}


def fixture(tmp_path, version=2):
    path = tmp_path / f"fixture-v{version}.db"
    subprocess.run([sys.executable, str(FIXTURE), str(path)], check=True)
    connection = sqlite3.connect(path)
    connection.execute(f"pragma user_version={version}")
    connection.commit(); connection.close()
    return path


def first_id(connection, table):
    return connection.execute(f'SELECT id FROM "{table}" LIMIT 1').fetchone()[0]


def test_all_legitimate_historical_nulls_are_preserved_and_response_serializable(tmp_path):
    # Build historical rows before migration installs canonical triggers; never
    # disable a production trigger to manufacture the fixture state.
    path = tmp_path / "pre-trigger-legacy.db"
    async def prepare():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            stamp = "2026-08-03T00:00:00+00:00"
            await connection.exec_driver_sql("INSERT INTO projects(id,name,status,created_at,updated_at,revision) VALUES('p','project','active',?,?,1)",(stamp,stamp))
            await connection.exec_driver_sql("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES('n','p','node','idea','active','seed','draft',?,?,1)",(stamp,stamp))
            await connection.exec_driver_sql("INSERT INTO edges(id,project_id,from_node_id,to_node_id,relation_type,weight,note,is_mainline,created_at,revision) VALUES('e','p','n','n','related_to',NULL,NULL,0,?,1)",(stamp,))
            await connection.exec_driver_sql("INSERT INTO content_blocks(id,node_id,block_type,content,order_index,created_at,updated_at,revision) VALUES('b','n','note','{}',0,?,?,1)",(stamp,stamp))
            for table, columns in LEGITIMATE_NULLS.items():
                await connection.exec_driver_sql(f'UPDATE "{table}" SET ' + ",".join(f'"{column}"=NULL' for column in columns))
            await migrate_sqlite(connection)
        await engine.dispose()
    asyncio.run(prepare())

    connection = sqlite3.connect(path); connection.row_factory = sqlite3.Row
    row_ids = {table: first_id(connection, table) for table in LEGITIMATE_NULLS}
    raw_rows = {table: dict(connection.execute(f'SELECT * FROM "{table}" WHERE id=?', (row_ids[table],)).fetchone()) for table in LEGITIMATE_NULLS}
    triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")}
    connection.close()
    assert "trg_edges_normalize_null_update" in triggers
    for table, columns in LEGITIMATE_NULLS.items():
        assert all(raw_rows[table][column] is None for column in columns), (table, raw_rows[table])
    status = dm.schema_status(path)
    assert status["compatible"] and not status["migrationNeeded"] and not status["reasons"], status

    async def serialize_through_orm():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            models = (await session.get(Project, row_ids["projects"]), await session.get(Node, row_ids["nodes"]), await session.get(Edge, row_ids["edges"]), await session.get(ContentBlock, row_ids["content_blocks"]))
            outputs = tuple(schema.model_validate(model) for schema, model in zip((ProjectOut, NodeOut, EdgeOut, ContentBlockOut), models))
        await engine.dispose()
        return outputs

    outputs = asyncio.run(serialize_through_orm())
    for output in outputs: assert output.model_dump(mode="json")
    for table, columns in LEGITIMATE_NULLS.items():
        dumped = outputs[list(LEGITIMATE_NULLS).index(table)].model_dump()
        assert all(dumped[column] is None for column in columns)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("table,columns", TIMESTAMPS.items())
def test_required_timestamp_null_fails_before_acceptance_or_version_advance(tmp_path, version, table, columns):
    path = fixture(tmp_path, version)
    connection = sqlite3.connect(path)
    row_id = first_id(connection, table)
    connection.execute(f'UPDATE "{table}" SET "{columns[-1]}"=NULL WHERE id=?', (row_id,))
    connection.commit(); connection.close()
    before = path.read_bytes()
    status = dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"]
    assert f"null_data:{table}.{columns[-1]}" in status["reasons"]
    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        with pytest.raises(RuntimeError, match=f"incompatible NULL data {table}.{columns[-1]}"):
            async with engine.begin() as connection:
                await migrate_sqlite(connection)
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("pragma user_version")).scalar() == version
        await engine.dispose()
    asyncio.run(run())
    # Rejected current-version databases are byte-identical; a v1 transaction
    # can transiently attempt additive DDL, but must preserve rows and version.
    if version == 2:
        assert path.read_bytes() == before


def test_required_timestamp_declarations_may_be_nullable_when_rows_are_valid(tmp_path):
    path = fixture(tmp_path, 2)
    status = dm.schema_status(path)
    assert status["compatible"] and not status["migrationNeeded"], status
    connection = sqlite3.connect(path)
    for table, columns in TIMESTAMPS.items():
        info = {row[1]: row for row in connection.execute(f'pragma table_info("{table}")')}
        assert all(not info[column][3] for column in columns)
    connection.close()
