"""Consistent pre-mutation backups for file-backed SQLite databases."""
from __future__ import annotations

import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from sqlalchemy.engine import make_url


def configured_sqlite_path(database_url: str) -> Path | None:
    """Resolve the database used by SQLAlchemy when it is a local SQLite file."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def _fsync_directory(path: Path) -> None:
    """Persist a rename on platforms that support opening directories."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_sqlite_file(source: Path, *, timeout_seconds: float = 15.0) -> Path:
    """Create one unique, verified SQLite backup next to the live database."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"configured database does not exist: {source}")

    destination = source.with_name(source.name + ".bak")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{source.name}.", suffix=".backup.tmp", dir=source.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    deadline = time.monotonic() + timeout_seconds

    try:
        source_uri = source.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=0.25)) as live:
            with closing(sqlite3.connect(temporary, timeout=0.25)) as backup:
                def progress(_status: int, _remaining: int, _total: int) -> None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out backing up SQLite database: {source}")

                live.backup(backup, pages=256, progress=progress, sleep=0.01)
                integrity = backup.execute("PRAGMA integrity_check").fetchone()
                if integrity != ("ok",):
                    raise RuntimeError(f"backup integrity check failed: {integrity!r}")
                backup.commit()

        # Windows requires a writable file descriptor for FlushFileBuffers,
        # which backs os.fsync(); r+b preserves bytes while making it portable.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(source.parent)
        return destination
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


async def backup_configured_database(database_url: str) -> Path | None:
    """Back up local SQLite; other database engines remain operator-managed."""
    source = configured_sqlite_path(database_url)
    if source is None:
        return None
    return await asyncio.to_thread(backup_sqlite_file, source)
