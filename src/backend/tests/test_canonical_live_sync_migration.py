"""Real, isolated v14 canonical-journal migration and safe-integer tests."""
import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.canonical_changes import change_hub
from api.revisions import MAX_SAFE_REVISION, claim_project_revision
from db.migrations import migrate_sqlite
from db.schema_contract import (
    CANONICAL_CHANGES_INDEX_SQL, TRIGGERS, normalize_default, normalize_sql,
)
from models.models import Base, CanonicalChange, Node, Project
from tests.generated_schema_fixtures import PROJECT, generate


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


async def _migrate(path: Path) -> None:
    engine = create_async_engine(_url(path))
    try:
        async with engine.begin() as conn:
            await migrate_sqlite(conn)
    finally:
        await engine.dispose()


def _schema_snapshot(path: Path):
    db = sqlite3.connect(path)
    try:
        return (
            db.execute("PRAGMA user_version").fetchone()[0],
            tuple(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type,name")),
            tuple(db.execute("SELECT * FROM projects ORDER BY id")),
        )
    finally:
        db.close()


def _journal_contract(db: sqlite3.Connection):
    info = tuple(db.execute("PRAGMA table_info(canonical_changes)"))
    indexes = tuple(db.execute("PRAGMA index_list(canonical_changes)"))
    index_info = tuple(db.execute("PRAGMA index_info(idx_canonical_changes_project_revision)"))
    sql = db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='canonical_changes'").fetchone()[0]
    return info, indexes, index_info, normalize_sql(sql)


def test_fresh_orm_and_migration_contract_have_identical_canonical_journal_schema_and_project_triggers(tmp_path):
    async def run():
        orm_path = tmp_path / "orm.db"
        migrated_path = tmp_path / "migrated.db"
        orm = create_async_engine(_url(orm_path))
        try:
            async with orm.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await orm.dispose()
        await _migrate(migrated_path := generate(migrated_path, "v13"))

        a, b = sqlite3.connect(orm_path), sqlite3.connect(migrated_path)
        try:
            ai, ax, axi, asql = _journal_contract(a)
            bi, bx, bxi, bsql = _journal_contract(b)
            # PRAGMA-visible type/null/default/PK shape, checks, and unique ordered index.
            shape = lambda rows: tuple((r[1], r[2].upper(), bool(r[3]), normalize_default(r[4]), r[5]) for r in rows)
            assert shape(ai) == shape(bi)
            # SQLAlchemy may spell a column-level PK as a table-level PK and may
            # place DEFAULT before NOT NULL. PRAGMA proves those equivalent
            # properties; normalized SQL proves both named CHECK predicates.
            for sql in (asql, bsql):
                assert "constraint ck_canonical_change_revision check(project_revision >=0 and project_revision <=9007199254740991)" in sql
                assert "constraint ck_canonical_change_kind check(kind in('graph','full_refresh','workspace'))" in sql
            assert [(r[1], bool(r[2]), bool(r[4])) for r in ax] == [(r[1], bool(r[2]), bool(r[4])) for r in bx]
            assert [r[2] for r in axi] == [r[2] for r in bxi] == ["project_id", "project_revision"]
            for name in ("trg_project_revision_safe_insert", "trg_project_revision_safe_update"):
                row = b.execute("SELECT type,tbl_name,sql FROM sqlite_schema WHERE name=?", (name,)).fetchone()
                assert row[:2] == ("trigger", "projects")
                assert normalize_sql(row[2]) == normalize_sql(TRIGGERS[name])
        finally:
            a.close(); b.close()
    asyncio.run(run())


def test_actual_v13_to_v14_then_orm_project_delete_persists_revision_zero_workspace_journal(tmp_path):
    async def run():
        path = generate(tmp_path / "delete.db", "v13")
        await _migrate(path)
        engine = create_async_engine(_url(path))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                project = await session.get(Project, PROJECT)
                await session.delete(project)
                await session.commit()
            async with maker() as session:
                assert await session.get(Project, PROJECT) is None
                row = (await session.execute(select(CanonicalChange).where(
                    CanonicalChange.project_id == PROJECT,
                    CanonicalChange.project_revision == 0))).scalar_one()
                assert row.kind == "workspace"
        finally:
            await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("sql_value", ("NULL", "'not-an-integer'", "1.5", "0", "9007199254740992"), ids=("null", "text", "real", "zero", "above-max"))
def test_malformed_v13_legacy_project_revision_fails_before_schema_or_user_version_change(tmp_path, sql_value):
    path = generate(tmp_path / "bad-revision.db", "v13")
    db = sqlite3.connect(path)
    try:
        db.execute("DROP TRIGGER trg_project_revision_safe_insert")
        db.execute("DROP TRIGGER trg_project_revision_safe_update")
        if sql_value == "NULL":
            sql = db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='projects'").fetchone()[0]
            sql = sql.replace("revision INTEGER NOT NULL DEFAULT 1", "revision INTEGER DEFAULT 1")
            db.execute("PRAGMA writable_schema=ON")
            db.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name='projects'", (sql,))
            db.execute("PRAGMA writable_schema=OFF")
            version = db.execute("PRAGMA schema_version").fetchone()[0]
            db.execute(f"PRAGMA schema_version={version + 1}")
        db.execute(f"UPDATE projects SET revision={sql_value} WHERE id=?", (PROJECT,))
        db.commit()
    finally:
        db.close()
    before = _schema_snapshot(path)
    with pytest.raises(RuntimeError, match="project revision outside exact JSON integer range"):
        asyncio.run(_migrate(path))
    assert _schema_snapshot(path) == before
    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT 1 FROM sqlite_schema WHERE name='canonical_changes'").fetchone() is None
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
    finally:
        db.close()


@pytest.mark.parametrize("replacement", (
    "CREATE INDEX idx_canonical_changes_project_revision ON canonical_changes(project_id,project_revision)",
    "CREATE UNIQUE INDEX idx_canonical_changes_project_revision ON canonical_changes(project_revision,project_id)",
    "CREATE UNIQUE INDEX idx_canonical_changes_project_revision ON canonical_changes(project_id,project_revision) WHERE project_revision>0",
), ids=("nonunique", "wrong-order", "partial"))
def test_current_canonical_journal_wrong_index_is_rejected_without_migration_mutation(tmp_path, replacement):
    path = generate(tmp_path / "bad-index.db", "v14")
    db = sqlite3.connect(path)
    db.execute("DROP INDEX idx_canonical_changes_project_revision"); db.execute(replacement); db.commit(); db.close()
    before = _schema_snapshot(path)
    with pytest.raises(RuntimeError, match="journal index"):
        asyncio.run(_migrate(path))
    assert _schema_snapshot(path) == before


@pytest.mark.parametrize("table_sql", (
    "CREATE TABLE canonical_changes (id VARCHAR(36) NOT NULL PRIMARY KEY,project_id VARCHAR(36) NOT NULL,project_revision INTEGER NOT NULL,kind VARCHAR(24) NOT NULL,hints JSON NOT NULL DEFAULT '{}',created_at DATETIME NOT NULL,CONSTRAINT ck_canonical_change_kind CHECK(kind IN ('graph','full_refresh','workspace')))",
    "CREATE TABLE canonical_changes (id VARCHAR(36) NOT NULL PRIMARY KEY,project_id VARCHAR(36) NOT NULL,project_revision INTEGER NOT NULL,kind VARCHAR(24) NOT NULL,hints JSON NOT NULL DEFAULT '{}',created_at DATETIME NOT NULL,CONSTRAINT ck_canonical_change_revision CHECK(project_revision>=0 AND project_revision<=9007199254740991),CONSTRAINT ck_canonical_change_kind CHECK(kind IN ('graph','workspace')))",
), ids=("missing-revision-check", "wrong-kind-check"))
def test_current_canonical_journal_missing_or_wrong_constraints_are_rejected(tmp_path, table_sql):
    path = generate(tmp_path / "bad-check.db", "v14")
    db = sqlite3.connect(path)
    db.execute("DROP TABLE canonical_changes"); db.execute(table_sql); db.execute(CANONICAL_CHANGES_INDEX_SQL); db.commit(); db.close()
    with pytest.raises(RuntimeError, match="canonical_changes (revision|kind) check"):
        asyncio.run(_migrate(path))


@pytest.mark.parametrize("row_sql", (
    "('x','p',1,'evil','{}','2026-01-01')",
    "('x','p',1.5,'graph','{}','2026-01-01')",
    "('x','p',1,'graph','{bad','2026-01-01')",
), ids=("invalid-kind", "real-revision", "bad-json"))
def test_validator_rejects_invalid_canonical_journal_rows_imported_with_checks_disabled(tmp_path, row_sql):
    path = generate(tmp_path / "bad-row.db", "v14")
    db = sqlite3.connect(path)
    db.execute("PRAGMA ignore_check_constraints=ON")
    db.execute(f"INSERT INTO canonical_changes VALUES {row_sql}")
    db.commit(); db.close()
    with pytest.raises(RuntimeError, match="journal data"):
        asyncio.run(_migrate(path))


def test_validator_rejects_duplicate_project_revision_rows_when_unique_index_was_replaced(tmp_path):
    path = generate(tmp_path / "duplicate.db", "v14")
    db = sqlite3.connect(path)
    db.execute("DROP INDEX idx_canonical_changes_project_revision")
    db.execute("CREATE INDEX idx_canonical_changes_project_revision ON canonical_changes(project_id,project_revision)")
    db.execute("INSERT INTO canonical_changes VALUES('a','p',1,'graph','{}','2026-01-01')")
    db.execute("INSERT INTO canonical_changes VALUES('b','p',1,'graph','{}','2026-01-01')")
    db.commit(); db.close()
    with pytest.raises(RuntimeError, match="journal index"):
        asyncio.run(_migrate(path))


def test_v14_migration_is_logically_idempotent_and_v15_is_rejected_unchanged(tmp_path):
    current = generate(tmp_path / "v15.db", "v15")
    before = _schema_snapshot(current)
    asyncio.run(_migrate(current)); asyncio.run(_migrate(current))
    assert _schema_snapshot(current) == before
    newer = generate(tmp_path / "v16.db", "newer_v16")
    newer_before = _schema_snapshot(newer)
    with pytest.raises(RuntimeError, match="newer than this application"):
        asyncio.run(_migrate(newer))
    assert _schema_snapshot(newer) == newer_before


def test_gui_claim_project_revision_max_minus_one_reaches_max_and_journals_exactly_once(tmp_path):
    async def run():
        path = tmp_path / "claim-ok.db"; engine = create_async_engine(_url(path))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                p = Project(name="near", revision=MAX_SAFE_REVISION - 1); session.add(p); await session.commit(); pid = p.id
                await session.execute(text("DELETE FROM canonical_changes WHERE project_id=:p"), {"p": pid}); await session.commit()
                claimed = await claim_project_revision(session, pid, MAX_SAFE_REVISION - 1)
                claimed.name = "at max"; await session.commit()
                rows = (await session.execute(select(CanonicalChange).where(CanonicalChange.project_id == pid))).scalars().all()
                assert claimed.revision == MAX_SAFE_REVISION
                assert len(rows) == 1 and rows[0].project_revision == MAX_SAFE_REVISION
        finally: await engine.dispose()
    asyncio.run(run())


def test_gui_claim_at_max_fails_without_entity_journal_wake_or_mutation(tmp_path):
    async def run():
        path = tmp_path / "claim-fail.db"; engine = create_async_engine(_url(path))
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        sub = change_hub.subscribe()
        try:
            async with maker() as session:
                p = Project(name="max", revision=MAX_SAFE_REVISION); session.add(p); await session.commit(); pid = p.id
                while not sub.queue.empty(): await change_hub.next(sub)
                await session.execute(text("DELETE FROM canonical_changes WHERE project_id=:p"), {"p": pid}); await session.commit()
                node = Node(project_id=pid, title="unchanged"); session.add(node); await session.commit(); nid = node.id
                while not sub.queue.empty(): await change_hub.next(sub)
                await session.execute(text("DELETE FROM canonical_changes WHERE project_id=:p"), {"p": pid}); await session.commit()
                node.title = "must roll back"
                with pytest.raises(HTTPException) as exc:
                    await claim_project_revision(session, pid, MAX_SAFE_REVISION)
                assert exc.value.status_code == 409 and exc.value.detail["code"] == "REVISION_EXHAUSTED"
                assert sub.queue.empty()
            async with maker() as verify:
                assert (await verify.get(Project, pid)).revision == MAX_SAFE_REVISION
                assert (await verify.get(Node, nid)).title == "unchanged"
                assert not (await verify.execute(select(CanonicalChange).where(CanonicalChange.project_id == pid))).scalars().all()
        finally:
            change_hub.unsubscribe(sub); await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("value", (None, "not-an-integer", 1.5, 0, 9007199254740992), ids=("null", "text", "real", "zero", "above-max"))
@pytest.mark.parametrize("operation", ("insert", "update"))
def test_real_sqlite_project_revision_triggers_reject_invalid_insert_and_update(tmp_path, value, operation):
    path = generate(tmp_path / f"trigger-{operation}.db", "v14")
    db = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="project revision outside safe integer range"):
            if operation == "insert":
                db.execute("INSERT INTO projects(id,name,status,created_at,updated_at,revision) VALUES('bad','bad','active','2026-01-01','2026-01-01',?)", (value,))
            else:
                db.execute("UPDATE projects SET revision=? WHERE id=?", (value, PROJECT))
        db.rollback()
        if operation == "insert": assert db.execute("SELECT 1 FROM projects WHERE id='bad'").fetchone() is None
        else: assert db.execute("SELECT revision FROM projects WHERE id=?", (PROJECT,)).fetchone()[0] == 7
    finally:
        db.close()
