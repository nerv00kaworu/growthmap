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
            "SELECT id, project_id, title, summary, node_type, status, maturity, "
            "priority, confidence, description, rules_text, constraints_text, examples_text, "
            "questions_text, decision_notes, tags, workflow_status, file_paths, created_by, "
            "last_edited_by, position_x, position_y, created_at, updated_at, revision FROM nodes"
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
        "",
        "root",
        "active",
        "seed",
        0,
        0.5,
        "",
        "",
        "",
        "",
        "",
        "",
        "[]",
        "draft",
        "[]",
        "human",
        "human",
        0.0,
        0.0,
        created_at,
        created_at,
        1,
    )


def test_e2e_fixture_serves_root_subtree_and_agent_activity_through_real_api(tmp_path):
    fixture = tmp_path / "fixture.sqlite"
    subprocess.run([sys.executable, str(SCRIPT), str(fixture)], check=True)
    backend = Path(__file__).resolve().parents[1]
    code = """\
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    response = client.get('/api/nodes/22222222-2222-4222-8222-222222222222/subtree')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == '22222222-2222-4222-8222-222222222222'
    assert body['project_id'] == '11111111-1111-4111-8111-111111111111'
    activity = client.get('/api/agent-port/activity?project_id=11111111-1111-4111-8111-111111111111')
    assert activity.status_code == 200, activity.text
    payload = activity.json()
    assert payload['proposals'] == []
    assert payload['events'] == []
    assert len(payload['readbacks']) == 2
    assert {row['summary'] for row in payload['readbacks']} == {'Packaged current implementation', 'Packaged stale implementation'}
"""
    env = dict(__import__('os').environ)
    env['DATABASE_URL'] = f"sqlite+aiosqlite:///{fixture}"
    result = subprocess.run([sys.executable, '-c', code], cwd=backend, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_e2e_fixture_refuses_live_looking_path():
    live_path = Path(__file__).resolve().parent / "growthmap.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(live_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "system temp directory" in result.stderr
    assert not live_path.exists()
