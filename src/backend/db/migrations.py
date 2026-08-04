"""Ordered fail-closed SQLite schema migrations."""
import os
from sqlalchemy import text
from db.schema_contract import CURRENT_USER_VERSION, COLUMNS, INDEX_SQL, TRIGGERS, ORM_READ_COLUMNS, ROW_REQUIRED_NON_NULL, column_matches, normalize_sql, orm_column_problem

async def _column(conn, table, name):
    rows=(await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()
    return next((row for row in rows if row[1]==name),None)

async def _validate_column(conn,spec):
    row=await _column(conn,spec[0],spec[1])
    if row is None:return False
    if not column_matches(row,spec):raise RuntimeError(f"incompatible migration column {spec[0]}.{spec[1]}")
    return True

async def _validate_orm_read_contract(conn):
    for table,columns in ORM_READ_COLUMNS.items():
        rows={row[1]:row for row in (await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()}
        for name,expected in columns.items():
            problem=orm_column_problem(rows.get(name),expected)
            if problem:raise RuntimeError(f"{problem} ORM read column {table}.{name}")

async def _validate_required_rows(conn):
    for table,columns in ROW_REQUIRED_NON_NULL.items():
        for column in columns:
            if (await conn.execute(text(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1'))).first():
                raise RuntimeError(f"incompatible NULL data {table}.{column}")

async def _validate_objects(conn,create_missing):
    expected={"ux_edges_one_mainline_per_parent":("index",INDEX_SQL),**{name:("trigger",sql) for name,sql in TRIGGERS.items()}}
    for name,(kind,sql) in expected.items():
        row=(await conn.execute(text("SELECT type,sql FROM sqlite_schema WHERE name=:name"),{"name":name})).first()
        if row is None:
            if not create_missing:raise RuntimeError(f"missing migration {kind} {name}")
            await conn.execute(text(sql));continue
        if row[0]!=kind or normalize_sql(row[1])!=normalize_sql(sql):raise RuntimeError(f"incompatible migration {kind} {name}")

async def migrate_sqlite(conn):
    version=int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
    if version>CURRENT_USER_VERSION:raise RuntimeError("database schema is newer than this application")
    upgrading=version<CURRENT_USER_VERSION
    for ordinal,spec in enumerate(COLUMNS,1):
        present=await _validate_column(conn,spec)
        if not present:
            if not upgrading:raise RuntimeError(f"missing migration column {spec[0]}.{spec[1]}")
            await conn.execute(text(spec[5]))
        if upgrading and os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER")==str(ordinal):raise RuntimeError("injected migration failure")
    await _validate_objects(conn,upgrading)
    for spec in COLUMNS:assert await _validate_column(conn,spec)
    # Missing non-migration-owned mapped columns are unsupported partial schemas.
    # Fail before advancing user_version rather than inventing data/defaults.
    await _validate_orm_read_contract(conn)
    await _validate_required_rows(conn)
    if upgrading:await conn.execute(text(f"PRAGMA user_version={CURRENT_USER_VERSION}"))
    if int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)!=CURRENT_USER_VERSION:raise RuntimeError("migration version did not validate")
