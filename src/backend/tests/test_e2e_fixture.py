import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "desktop" / "scripts" / "create-e2e-fixture.py"


def test_e2e_fixture_initializes_fresh_canonical_schema(tmp_path):
    fixture = tmp_path / "fixture.sqlite"

    subprocess.run([sys.executable, str(SCRIPT), str(fixture)], check=True)

    with sqlite3.connect(fixture) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name='projects'"
        ).fetchone()
        project = connection.execute(
            "SELECT id, name, description, goal, root_node_id, status, settings, "
            "created_at, updated_at, revision FROM projects"
        ).fetchone()
        root = connection.execute(
            "SELECT id, project_id, title, node_type, status, maturity, "
            "workflow_status, file_paths, revision FROM nodes"
        ).fetchone()
    project_id = "11111111-1111-4111-8111-111111111111"
    root_id = "22222222-2222-4222-8222-222222222222"
    created_at = "2026-07-30T00:00:00+00:00"
    assert table == ("projects",)
    assert project == (
        project_id,
        "Desktop Fixture",
        "",
        "",
        root_id,
        "active",
        "{}",
        created_at,
        created_at,
        1,
    )
    assert root == (
        root_id,
        project_id,
        "Desktop Fixture Root",
        "root",
        "active",
        "seed",
        "draft",
        "[]",
        1,
    )


def test_e2e_fixture_refuses_live_looking_path():
    live_path = Path(__file__).resolve().parent / "growthmap.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(live_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "system temp directory" in result.stderr
    assert not live_path.exists()
