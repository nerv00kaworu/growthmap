import asyncio, hashlib, sqlite3
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from db.migrations import migrate_sqlite
from db.schema_contract import REQUIRED_TABLE_COLUMNS, ORM_READ_COLUMNS
from desktop import database_maintenance as dm
from tests.generated_schema_fixtures import generate, logical_snapshot

MANDATORY=tuple(REQUIRED_TABLE_COLUMNS)
NON_ORM=tuple((table,column) for table,columns in REQUIRED_TABLE_COLUMNS.items() for column in sorted(columns-set(ORM_READ_COLUMNS.get(table,{}))))

def mutate(path, table, column=None):
    c=sqlite3.connect(path)
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        if column is None: c.execute(f'DROP TABLE "{table}"')
        else:
            info=c.execute(f'PRAGMA table_info("{table}")').fetchall()
            keep=[row[1] for row in info if row[1]!=column]
            defs=[]
            for row in info:
                if row[1]==column: continue
                definition=f'"{row[1]}" {row[2] or "BLOB"}'
                if row[5]: definition+=' PRIMARY KEY'
                if row[3]: definition+=' NOT NULL'
                if row[4] is not None: definition+=f' DEFAULT {row[4]}'
                defs.append(definition)
            c.execute(f'CREATE TABLE "broken_{table}"({",".join(defs)})')
            cols=','.join(f'"{name}"' for name in keep)
            c.execute(f'INSERT INTO "broken_{table}"({cols}) SELECT {cols} FROM "{table}"')
            c.execute(f'DROP TABLE "{table}"'); c.execute(f'ALTER TABLE "broken_{table}" RENAME TO "{table}"')
        c.commit()
    finally:c.close()

async def run_migration(path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{Path(path).as_posix()}")
    try:
        async with engine.begin() as connection: await migrate_sqlite(connection)
    finally: await engine.dispose()

@pytest.mark.parametrize("version",(11,12))
@pytest.mark.parametrize("table",MANDATORY)
def test_missing_mandatory_table_rejected_everywhere_before_mutation(tmp_path,version,table):
    path=generate(tmp_path/f"v{version}-{table}.db","v12")
    c=sqlite3.connect(path); c.execute(f"PRAGMA user_version={version}"); c.commit(); c.close()
    mutate(path,table); before=path.read_bytes(); logical=logical_snapshot(path)
    with pytest.raises(ValueError): dm.validate(path)
    status=dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"] and f"required_table:{table}" in status["reasons"]
    with pytest.raises(Exception): asyncio.run(run_migration(path))
    assert path.read_bytes()==before and logical_snapshot(path)==logical

@pytest.mark.parametrize("version",(11,12))
@pytest.mark.parametrize("table,column",NON_ORM)
def test_missing_non_orm_basic_column_rejected_everywhere_before_mutation(tmp_path,version,table,column):
    path=generate(tmp_path/f"v{version}-{table}-{column}.db","v12")
    c=sqlite3.connect(path); c.execute(f"PRAGMA user_version={version}"); c.commit(); c.close()
    mutate(path,table,column); before=path.read_bytes(); logical=logical_snapshot(path)
    with pytest.raises(ValueError): dm.validate(path)
    if (table,column)==("provider_configs","id"):
        with pytest.raises(ValueError,match="foreign key check failed"): dm.schema_status(path)
    else:
        status=dm.schema_status(path)
        assert not status["compatible"] and status["migrationNeeded"] and f"required_column:{table}.{column}" in status["reasons"]
    with pytest.raises(Exception): asyncio.run(run_migration(path))
    assert path.read_bytes()==before and logical_snapshot(path)==logical
