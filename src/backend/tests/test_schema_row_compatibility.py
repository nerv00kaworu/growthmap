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


CORE_DECLARATION_REQUIRED = {
    "projects": ("id", "created_at", "updated_at"),
    "nodes": ("id", "project_id", "created_at", "updated_at"),
    "edges": ("id", "project_id", "from_node_id", "to_node_id", "created_at"),
    "content_blocks": ("id", "node_id", "created_at", "updated_at"),
}


@pytest.mark.parametrize(
    "table,column",
    [(table, column) for table, columns in CORE_DECLARATION_REQUIRED.items() for column in columns],
)
def test_nullable_required_declaration_fails_preflight_and_migration(tmp_path, table, column):
    path = fixture(tmp_path, 2)
    connection = sqlite3.connect(path)
    row = next(row for row in connection.execute(f'pragma table_info("{table}")') if row[1] == column)
    declared = f'{column} {row[2]}' + (" PRIMARY KEY" if row[5] else "")
    canonical = declared + " NOT NULL"
    schema_sql = connection.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone()[0]
    assert canonical in schema_sql, (table, column, schema_sql)
    connection.execute("PRAGMA writable_schema=ON")
    connection.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name=?", (schema_sql.replace(canonical, declared, 1), table))
    connection.execute("PRAGMA writable_schema=OFF")
    connection.execute("PRAGMA schema_version=100")
    connection.commit(); connection.close()

    status = dm.schema_status(path)
    assert f"incompatible_orm_column:{table}.{column}" in status["reasons"], status

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        with pytest.raises(RuntimeError, match=f"incompatible ORM read column {table}.{column}"):
            async with engine.begin() as connection:
                await migrate_sqlite(connection)
        await engine.dispose()
    asyncio.run(run())


def test_canonical_declarations_are_not_null_but_value_fields_remain_nullable(tmp_path):
    path = fixture(tmp_path, dm.CURRENT_USER_VERSION)
    status = dm.schema_status(path)
    assert status["compatible"] and not status["migrationNeeded"], status
    connection = sqlite3.connect(path)
    for table, columns in CORE_DECLARATION_REQUIRED.items():
        info = {row[1]: row for row in connection.execute(f'pragma table_info("{table}")')}
        assert all(info[column][3] for column in columns)
    for table, columns in LEGITIMATE_NULLS.items():
        info = {row[1]: row for row in connection.execute(f'pragma table_info("{table}")')}
        assert all(not info[column][3] for column in columns)
    connection.close()
