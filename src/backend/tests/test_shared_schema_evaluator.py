import sqlite3
import pytest
from db.schema_contract import (CURRENT_USER_VERSION, OBJECT_METADATA, OBJECT_SQL,
    INDEXES, TRIGGERS, evaluate_snapshot, version_policy)
from desktop import database_maintenance as dm
from tests.generated_schema_fixtures import generate

@pytest.mark.parametrize("version",(0,2,8,9,11))
def test_version_policy_historical(version):
    p=version_policy(version)
    assert p["importableHistorical"] and p["migratable"] and not p["runnableCurrent"]

def test_version_policy_current_and_newer():
    assert version_policy(12)["runnableCurrent"]
    assert not version_policy(13)["supported"]
    assert version_policy(13)["newer"]

def test_object_metadata_is_total_exact():
    assert set(OBJECT_METADATA)==set(OBJECT_SQL)==set(INDEXES)|set(TRIGGERS)
    for name,meta in OBJECT_METADATA.items():
        assert meta["sql"]==OBJECT_SQL[name]
        assert meta["kind"] == ("index" if name in INDEXES else "trigger")
        assert meta["owner"]
        assert (dm.ALLOWED_INDEX_TABLES if meta["kind"]=="index" else dm.ALLOWED_TRIGGER_TABLES)[name]==meta["owner"]

def test_same_snapshot_drives_status_decision(tmp_path):
    path=generate(tmp_path/"v11.db","v11_no_selection")
    connection=sqlite3.connect(path)
    dm._configure(connection)
    result=evaluate_snapshot(dm._canonical_snapshot(connection)); connection.close()
    status=dm.schema_status(path)
    assert result["reasons"]==tuple(status["reasons"])
    assert result["compatibleCurrent"]==status["compatible"]
    assert result["migrationNeeded"]==status["migrationNeeded"]
    assert result["importable"] and result["migratable"]

def test_malformed_present_provider_is_never_migratable(tmp_path):
    path=generate(tmp_path/"bad.db","bad_selection_table")
    c=sqlite3.connect(path); c.execute("PRAGMA user_version=11"); c.commit(); dm._configure(c)
    result=evaluate_snapshot(dm._canonical_snapshot(c)); c.close()
    assert not result["importable"] and not result["migratable"]
    assert any(reason.startswith("provider_selection:") for reason in result["reasons"])

@pytest.mark.parametrize("version", (True, False, 1.0, 12.0, "12", None, -1, 13, 10**100))
def test_version_policy_rejects_hostile_values(version):
    policy=version_policy(version)
    assert not policy["supported"] and not policy["migratable"]
    assert policy["newer"] is (isinstance(version,int) and not isinstance(version,bool) and version>CURRENT_USER_VERSION)

@pytest.mark.parametrize("missing_table,reason", ((True,"required_table:action_logs"),(False,"required_column:action_logs.id")))
def test_required_contract_is_always_fatal_and_never_current_compatible(missing_table,reason):
    tables=set() if missing_table else {"action_logs"}
    snapshot={"version":CURRENT_USER_VERSION,"tables":tables,"tableInfo":{"action_logs":()},"objects":{},"enforceBasicRequired":False}
    result=evaluate_snapshot(snapshot)
    assert reason in result["reasons"]
    assert not result["importable"] and not result["compatibleCurrent"]
