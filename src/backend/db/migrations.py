"""Ordered fail-closed SQLite schema migrations."""
import os
import re
from sqlalchemy import text
from db.schema_contract import CURRENT_USER_VERSION, COLUMNS, TABLE_CONDITIONAL_COLUMNS, OBJECT_METADATA, ORM_READ_COLUMNS, ROW_REQUIRED_NON_NULL, PROVIDER_SELECTION_TABLE_SQL, applicable_objects, authority_critical_fk_violations, column_matches, normalize_sql, orm_column_problem, provider_selection_contract_problem, evaluate_snapshot

async def _canonical_snapshot(conn, foreign_key_rows=None):
    tables={row[0] for row in (await conn.execute(text("SELECT name FROM sqlite_schema WHERE type='table'"))).all()}
    infos={}
    for table in tables: infos[table]=(await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()
    objects={row[1]:(row[0],row[2]) for row in (await conn.execute(text("SELECT type,name,sql FROM sqlite_schema WHERE type IN ('index','trigger')"))).all()}
    nulls=[]
    for table,columns in ROW_REQUIRED_NON_NULL.items():
        present={row[1] for row in infos.get(table,())}
        for column in columns:
            if column in present and (await conn.execute(text(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1'))).first(): nulls.append((table,column))
    selection="provider_selection" in tables
    if foreign_key_rows is None: foreign_key_rows=(await conn.execute(text("PRAGMA foreign_key_check"))).all()
    return {"version":int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0),"tables":tables,"tableInfo":infos,"objects":objects,
      "nullViolations":nulls,"providerSelectionForeignKeys":(await conn.execute(text("PRAGMA foreign_key_list('provider_selection')"))).all() if selection else (),
      "providerSelectionSql":(await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='table' AND name='provider_selection'"))).scalar() if selection else None,
      "providerSelectionRows":(await conn.execute(text("SELECT singleton_id,provider_id,selection_revision,updated_at FROM provider_selection"))).all() if selection else (),
      "providerSelectionFkViolation":bool(authority_critical_fk_violations(foreign_key_rows))}

async def _table_exists(conn, table):
    return (await conn.execute(text("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=:name"), {"name":table})).first() is not None

async def _column(conn, table, name):
    rows=(await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()
    return next((row for row in rows if row[1]==name),None)

async def _validate_column(conn,spec):
    row=await _column(conn,spec[0],spec[1])
    if row is None:return False
    if not column_matches(row,spec):raise RuntimeError(f"incompatible migration column {spec[0]}.{spec[1]}")
    return True

async def _validate_orm_read_contract(conn, orm_read_columns=ORM_READ_COLUMNS):
    for table,columns in orm_read_columns.items():
        rows={row[1]:row for row in (await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()}
        for name,expected in columns.items():
            problem=orm_column_problem(rows.get(name),expected)
            if problem:raise RuntimeError(f"{problem} ORM read column {table}.{name}")

async def _migrate_agent_grant_expiry_nullable(conn,upgrading):
    if not await _table_exists(conn,"agent_grants"):return
    expiry=await _column(conn,"agent_grants","expires_at")
    if expiry is None:raise RuntimeError("missing ORM read column agent_grants.expires_at")
    if not bool(expiry[3]):return
    if not upgrading:raise RuntimeError("incompatible migration column agent_grants.expires_at")
    # SQLite cannot drop NOT NULL in place. Rename/add/copy/drop preserves expiry
    # values without replacing the table, so inbound FKs and indexes remain intact.
    await conn.execute(text("ALTER TABLE agent_grants RENAME COLUMN expires_at TO expires_at_legacy_v3"))
    await conn.execute(text("ALTER TABLE agent_grants ADD COLUMN expires_at DATETIME"))
    await conn.execute(text("UPDATE agent_grants SET expires_at=expires_at_legacy_v3"))
    await conn.execute(text("ALTER TABLE agent_grants DROP COLUMN expires_at_legacy_v3"))

async def _migrate_agent_grant_project_nullable(conn,upgrading):
    if not await _table_exists(conn,"agent_grants"):return
    project=await _column(conn,"agent_grants","project_id")
    if project is None:raise RuntimeError("missing ORM read column agent_grants.project_id")
    if not bool(project[3]):return
    if not upgrading:raise RuntimeError("incompatible migration column agent_grants.project_id")
    # Removing NOT NULL changes only SQLite schema metadata, not the record
    # format. Rebuilding/renaming this parent table is unsafe because SQLite
    # rewrites both its own FK and inbound proposal/event/readback FKs. Keep the
    # exact table and every row/index/FK identity, changing only the declaration.
    sql=(await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='table' AND name='agent_grants'"))).scalar()
    # Historical databases used both TEXT and VARCHAR(36) declarations.
    # Accept exactly those two compatible spellings and remove only NOT NULL.
    rewritten,count=re.subn(r'(?i)(\bproject_id\b\s+(?:TEXT|VARCHAR\s*\(\s*36\s*\)))\s+NOT\s+NULL',r'\1',sql,count=1)
    if count!=1:raise RuntimeError("unsupported legacy declaration agent_grants.project_id")
    await conn.execute(text("PRAGMA writable_schema=ON"))
    try:await conn.execute(text("UPDATE sqlite_schema SET sql=:sql WHERE type='table' AND name='agent_grants'"),{"sql":rewritten})
    finally:await conn.execute(text("PRAGMA writable_schema=OFF"))
    version=int((await conn.execute(text("PRAGMA schema_version"))).scalar())
    await conn.execute(text(f"PRAGMA schema_version={version+1}"))
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="agent_grant_project_v7":
        raise RuntimeError("injected migration failure after Agent Access v7 DDL")

async def _migrate_agent_grant_modes(conn,upgrading):
    """Map every legacy grant to its exact R18 mode without widening authority."""
    if not upgrading or not await _table_exists(conn,"agent_grants"):return
    await conn.execute(text("""
      UPDATE agent_grants
      SET workspace_scope='legacy_project',
          mode=CASE permission
            WHEN 'read' THEN 'read_only'
            WHEN 'propose' THEN 'review_first'
            WHEN 'write' THEN 'direct_collaboration'
            ELSE NULL END
      WHERE workspace_scope='legacy_project' AND mode IS NULL
    """))
    if (await conn.execute(text("SELECT 1 FROM agent_grants WHERE mode IS NULL OR mode NOT IN ('read_only','review_first','direct_collaboration') OR workspace_scope NOT IN ('legacy_project','workspace') OR (workspace_scope='workspace' AND project_id IS NOT NULL) OR (workspace_scope='legacy_project' AND project_id IS NULL) OR permission != CASE mode WHEN 'read_only' THEN 'read' WHEN 'review_first' THEN 'propose' WHEN 'direct_collaboration' THEN 'write' END LIMIT 1"))).first():
        raise RuntimeError("incompatible Agent Access v7 authority mapping")
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="agent_grant_modes_v7":
        raise RuntimeError("injected migration failure after Agent Access v7 mode mapping")

async def _validate_required_rows(conn):
    for table,columns in ROW_REQUIRED_NON_NULL.items():
        for column in columns:
            if (await conn.execute(text(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1'))).first():
                raise RuntimeError(f"incompatible NULL data {table}.{column}")

async def _demote_ambiguous_legacy_mainlines(conn, upgrading):
    """Apply the v5 owner-approved, custody-preserving ambiguity policy.

    For every legacy parent with two or more true child_of mainlines, demote all
    true mainlines in that group. IDs and rows are preserved; unambiguous,
    non-child, false and NULL markers are untouched. The predicate makes retry
    safe even when a SQLite driver retains earlier transactional DDL.
    """
    if not upgrading:return
    await conn.execute(text("""
      UPDATE edges SET is_mainline=0
      WHERE relation_type='child_of' AND is_mainline=1
        AND from_node_id IN (
          SELECT from_node_id FROM edges
          WHERE relation_type='child_of' AND is_mainline=1
          GROUP BY from_node_id HAVING COUNT(*)>1
        )
    """))
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER_MAINLINE_DEMOTION")=="1":
        raise RuntimeError("injected migration failure after mainline demotion")

# Legacy v0 declarations made these model-required timestamps nullable even
# though all ORM writes and response schemas require values. SQLite's documented
# generalized ALTER procedure permits changing only sqlite_schema when the
# on-disk row format is unchanged. Adding NOT NULL is such a metadata-only
# change: no value, ID, FK, index, trigger, or affinity is rewritten.
_LEGACY_REQUIRED_TIMESTAMP_COLUMNS = {
    "projects": ("created_at", "updated_at"),
    "nodes": ("created_at", "updated_at"),
    "edges": ("created_at",),
    "content_blocks": ("created_at", "updated_at"),
}


async def _validate_before_mutation(conn, migration_specs, upgrading, version, orm_read_columns=ORM_READ_COLUMNS):
    """Reject unsupported/NULL legacy states before the first write."""
    if await _table_exists(conn, "provider_configs") and await _column(conn, "provider_configs", "revision"):
        if (await conn.execute(text("SELECT 1 FROM provider_configs WHERE typeof(revision) != 'integer' OR revision < 1 OR revision > 9007199254740991 LIMIT 1"))).first():
            raise RuntimeError("provider revision outside exact JSON integer range")
    for spec in migration_specs:
        row = await _column(conn, spec[0], spec[1])
        if row is not None and not column_matches(row, spec):
            raise RuntimeError(f"incompatible migration column {spec[0]}.{spec[1]}")
        if row is None and not upgrading:
            raise RuntimeError(f"missing migration column {spec[0]}.{spec[1]}")
    additive={(spec[0],spec[1]) for spec in migration_specs}
    for table, columns in orm_read_columns.items():
        rows = {row[1]: row for row in (await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()}
        for name, expected in columns.items():
            problem = orm_column_problem(rows.get(name), expected)
            repairable = upgrading and (
                (problem == "missing" and (table,name) in additive) or
                (version == 0 and problem == "incompatible" and
                 name in _LEGACY_REQUIRED_TIMESTAMP_COLUMNS.get(table, ()) and
                 rows[name][2].upper() in ("DATETIME", "TIMESTAMP") and not bool(rows[name][3]))
            )
            if problem and not repairable:
                raise RuntimeError(f"{problem} ORM read column {table}.{name}")
    await _validate_required_rows(conn)
    # Existing objects with a canonical name must be exact. Missing objects are
    # migration-owned and may be created only after every preflight passes.
    await _validate_objects(conn, False if not upgrading else None)


async def _validate_objects(conn, create_missing):
    tables={row[0] for row in (await conn.execute(text("SELECT name FROM sqlite_schema WHERE type='table'"))).all()}
    expected=applicable_objects(tables)
    for name,sql in expected.items():
        kind=OBJECT_METADATA[name]["kind"]
        row=(await conn.execute(text("SELECT type,sql FROM sqlite_schema WHERE name=:name"),{"name":name})).first()
        if row is None:
            if create_missing is False:raise RuntimeError(f"missing migration {kind} {name}")
            if create_missing is True:await conn.execute(text(sql))
            continue
        if row[0]!=kind or normalize_sql(row[1])!=normalize_sql(sql):raise RuntimeError(f"incompatible migration {kind} {name}")


async def _enforce_legacy_required_timestamps(conn, upgrading, version):
    if not upgrading or version != 0:return
    replacements={}
    for table,columns in _LEGACY_REQUIRED_TIMESTAMP_COLUMNS.items():
        rows={row[1]:row for row in (await conn.execute(text(f'PRAGMA table_info("{table}")'))).all()}
        nullable=[column for column in columns if not bool(rows[column][3])]
        if not nullable:continue
        sql=(await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='table' AND name=:name"),{"name":table})).scalar()
        rewritten=sql
        for column in nullable:
            pattern=rf'(?i)(\b{re.escape(column)}\b\s+(?:DATETIME|TIMESTAMP))(?!\s+NOT\s+NULL)'
            rewritten,count=re.subn(pattern,r'\1 NOT NULL',rewritten,count=1)
            if count!=1:raise RuntimeError(f"unsupported legacy declaration {table}.{column}")
        replacements[table]=rewritten
    if not replacements:return
    await conn.execute(text("PRAGMA writable_schema=ON"))
    try:
        for table,sql in replacements.items():
            await conn.execute(text("UPDATE sqlite_schema SET sql=:sql WHERE type='table' AND name=:name"),{"sql":sql,"name":table})
    finally:
        await conn.execute(text("PRAGMA writable_schema=OFF"))
    version=int((await conn.execute(text("PRAGMA schema_version"))).scalar())
    await conn.execute(text(f"PRAGMA schema_version={version+1}"))
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="timestamp_ddl":
        raise RuntimeError("injected migration failure after timestamp DDL")


async def _validate_provider_selection_contract(conn, require_row=True):
    info=(await conn.execute(text("PRAGMA table_info('provider_selection')"))).all()
    foreign_keys=(await conn.execute(text("PRAGMA foreign_key_list('provider_selection')"))).all()
    sql=(await conn.execute(text("SELECT sql FROM sqlite_schema WHERE type='table' AND name='provider_selection'"))).scalar()
    problem=provider_selection_contract_problem(info,foreign_keys,sql)
    if problem: raise RuntimeError(f"incompatible provider_selection authority table: {problem}")
    rows=(await conn.execute(text("SELECT singleton_id,provider_id,selection_revision,updated_at FROM provider_selection"))).all()
    if require_row and len(rows)!=1: raise RuntimeError("missing or duplicate provider_selection singleton row")
    if rows:
        row=rows[0]
        if row[0]!=1 or not isinstance(row[2],int) or not 1<=row[2]<=9007199254740991 or row[3] is None:
            raise RuntimeError("incompatible provider_selection singleton row")


async def _migrate_sqlite_body(conn):
    version=int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)
    if version>CURRENT_USER_VERSION:raise RuntimeError("database schema is newer than this application")
    upgrading=version<CURRENT_USER_VERSION
    # Preserve the pre-existing FK custody state. Legacy authoring fixtures may
    # contain unrelated historical violations; migration must add none.
    foreign_keys_before=(await conn.execute(text("PRAGMA foreign_key_check"))).all()
    if authority_critical_fk_violations(foreign_keys_before):
        raise RuntimeError("provider selection authority foreign key violation")
    migration_specs=list(COLUMNS)
    for spec in TABLE_CONDITIONAL_COLUMNS:
        if await _table_exists(conn,spec[0]):migration_specs.append(spec)
    selection_exists = await _table_exists(conn, "provider_selection")
    if not selection_exists and not upgrading: raise RuntimeError("missing provider_selection authority table")
    if selection_exists:
        await _validate_provider_selection_contract(conn, require_row=False)
    # Per-call immutable view: concurrent migrations must never observe a mutated
    # process-global schema contract while the v12 authority table is being born.
    preflight_contract = ORM_READ_COLUMNS if selection_exists else {table: columns for table, columns in ORM_READ_COLUMNS.items() if table != "provider_selection"}
    await _validate_before_mutation(conn,migration_specs,upgrading,version,preflight_contract)
    shared_preflight=evaluate_snapshot(await _canonical_snapshot(conn, foreign_keys_before))
    if upgrading and not shared_preflight["migratable"]: raise RuntimeError("incompatible canonical schema before migration: "+shared_preflight["reasons"][0])
    if not upgrading and not shared_preflight["compatibleCurrent"]: raise RuntimeError("incompatible current canonical schema singleton: "+shared_preflight["reasons"][0])
    if not selection_exists:
        await conn.execute(text(PROVIDER_SELECTION_TABLE_SQL))
        await conn.execute(text("INSERT INTO provider_selection(singleton_id,provider_id,selection_revision,updated_at) VALUES(1,NULL,1,CURRENT_TIMESTAMP)"))
        if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="provider_selection_v12":
            raise RuntimeError("injected migration failure after provider selection DDL")
    elif not (await conn.execute(text("SELECT 1 FROM provider_selection WHERE singleton_id=1"))).first():
        if not upgrading:
            # Once v12 is authoritative, a missing singleton is corruption and
            # must never be recreated silently.
            raise RuntimeError("missing provider_selection singleton row")
        # SQLAlchemy create_all() runs before migrations and may materialize the
        # new v12 table on a v0-v11 database.  Seed only the empty authority
        # container while upgrading; provider_id stays NULL, so no provider is
        # inferred or selected from legacy/user data.
        if (await conn.execute(text("SELECT 1 FROM provider_selection LIMIT 1"))).first():
            raise RuntimeError("malformed provider_selection rows before v12 upgrade")
        await conn.execute(text("INSERT INTO provider_selection(singleton_id,provider_id,selection_revision,updated_at) VALUES(1,NULL,1,CURRENT_TIMESTAMP)"))
    await _validate_provider_selection_contract(conn)
    await _enforce_legacy_required_timestamps(conn,upgrading,version)
    for ordinal,spec in enumerate(migration_specs,1):
        present=await _validate_column(conn,spec)
        if not present:
            await conn.execute(text(spec[5]))
        if upgrading and os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER")==str(ordinal):raise RuntimeError("injected migration failure")
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="additive_ddl":raise RuntimeError("injected migration failure after additive DDL")
    await _migrate_agent_grant_expiry_nullable(conn,upgrading)
    await _migrate_agent_grant_project_nullable(conn,upgrading)
    await _migrate_agent_grant_modes(conn,upgrading)
    await _demote_ambiguous_legacy_mainlines(conn,upgrading)
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="option2":raise RuntimeError("injected migration failure after Option2")
    await _validate_objects(conn,upgrading)
    if os.getenv("GROWTHMAP_TEST_FAIL_MIGRATION_PHASE")=="objects":raise RuntimeError("injected migration failure after objects")
    for spec in migration_specs:assert await _validate_column(conn,spec)
    await _validate_orm_read_contract(conn)
    await _validate_required_rows(conn)
    if (await conn.execute(text("PRAGMA integrity_check"))).scalar()!="ok":raise RuntimeError("database integrity check failed after migration")
    if (await conn.execute(text("PRAGMA foreign_key_check"))).all()!=foreign_keys_before:raise RuntimeError("database foreign key state changed after migration")
    if upgrading:await conn.execute(text(f"PRAGMA user_version={CURRENT_USER_VERSION}"))
    if int((await conn.execute(text("PRAGMA user_version"))).scalar() or 0)!=CURRENT_USER_VERSION:raise RuntimeError("migration version did not validate")
    shared_final=evaluate_snapshot(await _canonical_snapshot(conn, foreign_keys_before))
    if not shared_final["compatibleCurrent"]: raise RuntimeError("migration final canonical contract did not validate: "+shared_final["reasons"][0])


async def migrate_sqlite(conn):
    # SAVEPOINT makes every migration-owned schema/data/object/version write one
    # rollback unit, including SQLite DDL and writable_schema metadata changes.
    # It also composes with the application's engine.begin() transaction.
    savepoint=await conn.begin_nested()
    try:
        await _migrate_sqlite_body(conn)
    except BaseException:
        await savepoint.rollback()
        raise
    else:
        await savepoint.commit()
