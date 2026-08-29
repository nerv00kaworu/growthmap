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
        provider_columns = {
            column[1] for column in connection.execute("PRAGMA table_info(provider_configs)")
        }
        connection.execute(
            """INSERT INTO provider_configs(
                id,name,provider_type,endpoint,auth_type,secret_env_key,model_name,
                capabilities,cost_level,enabled,settings,created_at,updated_at,
                revision,secret_change_pending,secret_change_claim
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "provider", "Fixture Provider", "openai_compatible",
                "http://127.0.0.1:9", "env", "GROWTHMAP_LLM_KEY_E2E", "fixture",
                "[]", "none", 1, "{}", None, None, 1, 0, None,
            ),
        )
        provider = connection.execute(
            "SELECT id, provider_type, revision, secret_change_pending FROM provider_configs"
        ).fetchone()
    assert table == ("projects",)
    assert row == ("fixture", "Desktop Fixture", "active")
    assert provider_columns == {
        "id", "name", "provider_type", "endpoint", "auth_type", "secret_env_key",
        "model_name", "capabilities", "cost_level", "enabled", "settings",
        "created_at", "updated_at", "revision", "secret_change_pending",
        "secret_change_claim",
    }
    assert provider == ("provider", "openai_compatible", 1, 0)


def test_e2e_fixture_refuses_live_looking_path():
    live_path = Path(__file__).resolve().parent / "growthmap.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(live_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "system temp directory" in result.stderr
    assert not live_path.exists()
