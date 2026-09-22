import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock

import pytest

from api import database_backup, routes


def test_backup_captures_committed_wal_and_preserves_live_database(tmp_path):
    source = tmp_path / "configured.db"
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE values_table(value TEXT NOT NULL)")
        writer.execute("INSERT INTO values_table VALUES ('committed-in-wal')")
        writer.commit()
        wal = Path(f"{source}-wal")
        assert wal.is_file() and wal.stat().st_size > 0

        destination = database_backup.backup_sqlite_file(source)

        assert destination == Path(f"{source}.bak")
        with closing(sqlite3.connect(destination)) as copied:
            assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert copied.execute("SELECT value FROM values_table").fetchone() == ("committed-in-wal",)
        assert writer.execute("SELECT value FROM values_table").fetchone() == ("committed-in-wal",)


def test_missing_source_is_not_created(tmp_path):
    source = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        database_backup.backup_sqlite_file(source)
    assert not source.exists()


def test_configured_path_and_unsupported_database_modes(tmp_path):
    source = tmp_path / "custom.db"
    assert database_backup.configured_sqlite_path(f"sqlite+aiosqlite:///{source}") == source.resolve()
    assert database_backup.configured_sqlite_path("sqlite+aiosqlite:///:memory:") is None
    assert database_backup.configured_sqlite_path("postgresql+asyncpg://localhost/growthmap") is None


def test_backup_atomically_refreshes_one_rolling_copy(tmp_path):
    source = tmp_path / "configured.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE keep(value TEXT)")
        connection.commit()
    destination = database_backup.backup_sqlite_file(source)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("INSERT INTO keep VALUES ('latest')")
        connection.commit()
    refreshed = database_backup.backup_sqlite_file(source)
    assert refreshed == destination == Path(f"{source}.bak")
    with closing(sqlite3.connect(refreshed)) as copied:
        assert copied.execute("SELECT value FROM keep").fetchall() == [("latest",)]
    assert not list(tmp_path.glob("*.backup.tmp"))


def test_backup_preserves_preexisting_foreign_key_violation_for_recovery(tmp_path):
    source = tmp_path / "invalid.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.executescript(
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id));"
            "INSERT INTO child VALUES(99);"
        )
        connection.commit()
    destination = database_backup.backup_sqlite_file(source)
    with closing(sqlite3.connect(destination)) as copied:
        copied.execute("PRAGMA foreign_keys=ON")
        assert copied.execute("PRAGMA foreign_key_check").fetchall()
        assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize("endpoint,name", [(routes.delete_project, "project"), (routes.delete_node, "node")])
def test_failed_backup_precedes_destructive_database_access(monkeypatch, endpoint, name):
    database = type("Database", (), {"get": AsyncMock(), "delete": AsyncMock(), "commit": AsyncMock()})()
    monkeypatch.setattr(routes, "backup_configured_database", AsyncMock(side_effect=RuntimeError("backup failed")))
    with pytest.raises(RuntimeError, match="backup failed"):
        asyncio.run(endpoint(name, object(), database))
    database.get.assert_not_awaited()
    database.delete.assert_not_awaited()
    database.commit.assert_not_awaited()
