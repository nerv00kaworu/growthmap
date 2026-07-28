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
        row = connection.execute(
            "SELECT id, name, status FROM projects WHERE id='fixture'"
        ).fetchone()
    assert table == ("projects",)
    assert row == ("fixture", "Desktop Fixture", "active")


def test_e2e_fixture_refuses_live_looking_path():
    live_path = Path(__file__).resolve().parent / "growthmap.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(live_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "system temp directory" in result.stderr
    assert not live_path.exists()
