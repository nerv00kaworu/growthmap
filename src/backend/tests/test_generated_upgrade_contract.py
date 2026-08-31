import asyncio
import hashlib
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from db.migrations import migrate_sqlite
from db.schema_contract import CURRENT_USER_VERSION, OBJECT_SQL, applicable_objects, authority_critical_fk_violations, provider_selection_contract_problem
from desktop import database_maintenance as dm
from tests.generated_schema_fixtures import GRANT, PROJECT, PROVIDER, generate, logical_snapshot

HISTORICAL = (
    "v2", "grant_nullable_legacy", "grant_not_null_missing",
    "v8_no_provider_revision", "v9_provider_revision", "v11_no_selection",
)
NEAR_MISSES = (
    "newer_v14", "bad_column", "missing_object", "forged_object",
    "bad_selection_table", "bad_selection_missing_row", "bad_selection_row",
)


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def migrate(path):
    # Exact absolute tmp_path URL: never consult DATABASE_URL or a default DB.
    assert Path(path).is_absolute()
    engine=create_async_engine(f"sqlite+aiosqlite:///{Path(path).as_posix()}")
    try:
        async with engine.begin() as connection: await migrate_sqlite(connection)
    finally: await engine.dispose()


def sql_snapshot(path):
    c=sqlite3.connect(path)
    try:
        return {
            "version":c.execute("PRAGMA user_version").fetchone()[0],
            "integrity":c.execute("PRAGMA integrity_check").fetchone()[0],
            "fk":c.execute("PRAGMA foreign_key_check").fetchall(),
            "project":c.execute("SELECT id,name FROM projects").fetchall(),
            "provider":c.execute("SELECT id,name FROM provider_configs").fetchall(),
            "grant":c.execute("SELECT id,project_id,permission,expires_at FROM agent_grants").fetchall() if c.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='agent_grants'").fetchone() else [],
            "objects":c.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type,name").fetchall(),
        }
    finally:c.close()


@pytest.mark.parametrize("variant", HISTORICAL)
def test_generated_history_crosses_read_only_maintenance_and_writable_migration(tmp_path, variant):
    path=generate(tmp_path/f"{variant}.db",variant)
    meta=dm.validate(path)
    assert meta["valid"] and meta["userVersion"] < CURRENT_USER_VERSION
    status=dm.schema_status(path)
    assert status["migrationNeeded"] and not status["compatible"]
    assert f"user_version:{meta['userVersion']}" in status["reasons"]
    before=sql_snapshot(path)

    asyncio.run(migrate(path))

    assert dm.validate(path)["valid"]
    status=dm.schema_status(path)
    assert status["compatible"] and not status["migrationNeeded"] and status["reasons"] == []
    after=sql_snapshot(path)
    assert after["version"] == CURRENT_USER_VERSION
    assert after["integrity"] == "ok" and after["fk"] == []
    assert after["project"] == before["project"]
    assert after["provider"] == before["provider"]
    assert after["grant"] == before["grant"]
    assert after["project"][0][0] == PROJECT and after["provider"][0][0] == PROVIDER
    if variant.startswith("grant_"):
        assert after["grant"][0][0] == GRANT
        c=sqlite3.connect(path); row=c.execute("SELECT persistent,workspace_scope,mode FROM agent_grants WHERE id=?",(GRANT,)).fetchone(); expiry=c.execute("PRAGMA table_info(agent_grants)").fetchall(); c.close()
        assert row == (0,"legacy_project","review_first")
        assert not bool(next(item for item in expiry if item[1]=="expires_at")[3])


def test_v11_absence_is_historical_not_hostile_and_seeds_exact_authority(tmp_path):
    path=generate(tmp_path/"v11.db","v11_no_selection")
    assert dm.validate(path)["valid"]
    reasons=dm.schema_status(path)["reasons"]
    assert "missing_orm_column:provider_selection.singleton_id" in reasons
    asyncio.run(migrate(path))
    c=sqlite3.connect(path)
    info=c.execute("PRAGMA table_info(provider_selection)").fetchall()
    fks=c.execute("PRAGMA foreign_key_list(provider_selection)").fetchall()
    sql=c.execute("SELECT sql FROM sqlite_schema WHERE name='provider_selection'").fetchone()[0]
    row=c.execute("SELECT singleton_id,provider_id,selection_revision,updated_at FROM provider_selection").fetchone()
    c.close()
    assert provider_selection_contract_problem(info,fks,sql) is None
    assert row[:3] == (1,None,1) and row[3] is not None


def test_generic_current_acceptance_and_migration_are_byte_idempotent(tmp_path):
    path=generate(tmp_path/"generic-v13.db","v13")
    assert dm.validate(path)["valid"]
    status=dm.schema_status(path)
    assert status["compatible"] and not status["migrationNeeded"]
    before_bytes=path.read_bytes(); before_logical=logical_snapshot(path)
    asyncio.run(migrate(path))
    assert path.read_bytes() == before_bytes
    assert logical_snapshot(path) == before_logical
    # A second production writable startup/migration call is equally inert.
    asyncio.run(migrate(path))
    assert path.read_bytes() == before_bytes


def test_generator_is_logically_deterministic(tmp_path):
    for variant in HISTORICAL + ("v12","v13",) + NEAR_MISSES:
        one=generate(tmp_path/f"one-{variant}.db",variant)
        two=generate(tmp_path/f"two-{variant}.db",variant)
        assert logical_snapshot(one) == logical_snapshot(two), variant


@pytest.mark.parametrize("variant", NEAR_MISSES)
def test_current_near_misses_are_fail_closed_without_migration_mutation(tmp_path, variant):
    path=generate(tmp_path/f"near-{variant}.db",variant)
    before_bytes=path.read_bytes(); before=sql_snapshot(path)
    with pytest.raises(ValueError): dm.validate(path)
    if variant in ("newer_v14","bad_selection_table","bad_selection_row"):
        with pytest.raises(ValueError): dm.schema_status(path)
    else:
        status=dm.schema_status(path)
        assert not status["compatible"] and status["migrationNeeded"] and status["reasons"]
    with pytest.raises(RuntimeError): asyncio.run(migrate(path))
    assert path.read_bytes() == before_bytes
    assert sql_snapshot(path) == before


def test_optional_object_applicability_is_shared_and_owner_driven(tmp_path):
    absent=generate(tmp_path/"absent.db","v2")
    present=generate(tmp_path/"present.db","v13")
    for path, expected_optional in ((absent,False),(present,True)):
        c=sqlite3.connect(path)
        tables={row[0] for row in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        c.close()
        applicable=applicable_objects(tables)
        assert set(applicable) <= set(OBJECT_SQL)
        assert ("ux_agent_grants_one_active_workspace" in applicable) is expected_optional
    rows=[("provider_selection",1,"provider_configs",0),("historical_orphans",2,"projects",0)]
    assert authority_critical_fk_violations(rows) == (rows[0],)


@pytest.mark.parametrize("variant", ("missing_optional_index","forged_optional_index"))
def test_current_optional_index_drift_fails_closed_without_mutation(tmp_path, variant):
    path=generate(tmp_path/f"{variant}.db",variant)
    with pytest.raises(ValueError): dm.validate(path)
    status=dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"] and status["reasons"]
    before=path.read_bytes()
    with pytest.raises(RuntimeError): asyncio.run(migrate(path))
    assert path.read_bytes()==before


def test_historical_missing_optional_index_is_repaired(tmp_path):
    path=generate(tmp_path/"historical-index.db","missing_optional_index")
    c=sqlite3.connect(path); c.execute("PRAGMA user_version=11"); c.commit(); c.close()
    asyncio.run(migrate(path))
    assert dm.schema_status(path)["compatible"]


def test_historical_unrelated_fk_violation_is_preserved(tmp_path):
    path=generate(tmp_path/"historical-fk.db","historical_unrelated_fk")
    c=sqlite3.connect(path); before=c.execute("PRAGMA foreign_key_check").fetchall(); c.close()
    assert before and not authority_critical_fk_violations(before)
    asyncio.run(migrate(path))
    c=sqlite3.connect(path); after=c.execute("PRAGMA foreign_key_check").fetchall(); version=c.execute("PRAGMA user_version").fetchone()[0]; c.close()
    assert after==before and version==CURRENT_USER_VERSION

@pytest.mark.parametrize("variant",("bad_column","forged_object"))
def test_historical_malformed_present_schema_rejected_consistently(tmp_path,variant):
    path=generate(tmp_path/f"historical-{variant}.db",variant)
    c=sqlite3.connect(path); c.execute("PRAGMA user_version=11"); c.commit(); c.close()
    before=path.read_bytes(); logical=logical_snapshot(path)
    with pytest.raises(ValueError): dm.validate(path)
    status=dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"]
    expected={"bad_column":"incompatible_orm_column:projects.settings","forged_object":"incompatible_object:trg_edges_normalize_null_insert"}[variant]
    assert expected in status["reasons"]
    with pytest.raises(RuntimeError): asyncio.run(migrate(path))
    assert path.read_bytes()==before and logical_snapshot(path)==logical


def test_historical_required_null_data_rejected_consistently(tmp_path):
    path=generate(tmp_path/"historical-null.db","v13")
    c=sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=OFF")
    sql=c.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='projects'").fetchone()[0]
    c.execute("PRAGMA writable_schema=ON")
    c.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name='projects'",(sql.replace('name TEXT NOT NULL','name TEXT'),))
    c.execute("PRAGMA writable_schema=OFF"); version=c.execute("PRAGMA schema_version").fetchone()[0]; c.execute(f"PRAGMA schema_version={version+1}")
    c.execute("UPDATE projects SET name=NULL"); c.execute("PRAGMA user_version=11"); c.commit(); c.close()
    before=path.read_bytes(); logical=logical_snapshot(path)
    with pytest.raises(ValueError): dm.validate(path)
    status=dm.schema_status(path)
    assert not status["compatible"] and status["migrationNeeded"] and "incompatible_orm_column:projects.name" in status["reasons"]
    with pytest.raises(RuntimeError): asyncio.run(migrate(path))
    assert path.read_bytes()==before and logical_snapshot(path)==logical


def test_historical_missing_object_is_importable_and_repaired(tmp_path):
    path=generate(tmp_path/"historical-missing-object.db","missing_object")
    c=sqlite3.connect(path); c.execute("PRAGMA user_version=11"); c.commit(); c.close()
    assert dm.validate(path)["valid"]
    status=dm.schema_status(path); assert status["migrationNeeded"] and "object:trg_edges_normalize_null_insert" in status["reasons"]
    asyncio.run(migrate(path))
    assert dm.schema_status(path)["compatible"]
