import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db.migrations import migrate_sqlite
from db.schema_contract import CURRENT_USER_VERSION, INDEX_SQL, TRIGGERS, normalize_sql


async def _legacy_engine(tmp_path):
    from db.database import Base
    from models import models  # noqa: F401

    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'option2.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("INSERT INTO projects(id,name,status,created_at,updated_at,revision) VALUES('p','kept','active','2026-01-01','2026-01-01',1)"))
        for i in range(12):
            await conn.execute(text("INSERT INTO nodes(id,project_id,title,node_type,status,maturity,workflow_status,created_at,updated_at,revision) VALUES(:id,'p',:id,'topic','active','seed','draft','2026-01-01','2026-01-01',1)"),{"id":f"n{i}"})
        rows=[
          # ambiguous groups of 2 and 6: every true marker must be demoted
          ("a1","n0","n1","child_of",1),("a2","n0","n2","child_of",1),
          *[(f"b{i}","n3",f"n{i+4}","child_of",1) for i in range(6)],
          # exact-one child mainline and unrelated true marker stay unchanged
          ("single","n1","n2","child_of",1),("false","n1","n3","child_of",0),
          ("related","n2","n3","related_to",1),
        ]
        for edge_id,parent,child,kind,mainline in rows:
            await conn.execute(text("INSERT INTO edges(id,project_id,from_node_id,to_node_id,relation_type,is_mainline,created_at,revision) VALUES(:id,'p',:parent,:child,:kind,:mainline,'2026-01-01',1)"),{"id":edge_id,"parent":parent,"child":child,"kind":kind,"mainline":mainline})
        await conn.execute(text(f"PRAGMA user_version={CURRENT_USER_VERSION-1}"))
    return engine


async def _option2_policy_is_exact_and_idempotent(tmp_path):
    engine=await _legacy_engine(tmp_path)
    async with engine.connect() as conn:
        before_counts=[]
        for table in ("nodes","edges"):
            before_counts.append((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar())
        before_counts=tuple(before_counts)
        before_ids=[r[0] for r in (await conn.execute(text("SELECT id FROM edges ORDER BY id"))).all()]
    async with engine.begin() as conn:await migrate_sqlite(conn)
    async with engine.begin() as conn:await migrate_sqlite(conn)
    async with engine.connect() as conn:
        after_counts=[]
        for table in ("nodes","edges"):
            after_counts.append((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar())
        after_counts=tuple(after_counts)
        assert after_counts==before_counts==(12,11)
        assert [r[0] for r in (await conn.execute(text("SELECT id FROM edges ORDER BY id"))).all()]==before_ids
        values=dict((await conn.execute(text("SELECT id,is_mainline FROM edges"))).all())
        assert all(values[e]==0 for e in ("a1","a2",*(f"b{i}" for i in range(6))))
        assert values["single"]==1 and values["false"]==0 and values["related"]==1
        assert (await conn.execute(text("SELECT count(*) FROM (SELECT from_node_id FROM edges WHERE relation_type='child_of' AND is_mainline=1 GROUP BY from_node_id HAVING count(*)>1)"))).scalar()==0
        assert (await conn.execute(text("PRAGMA user_version"))).scalar()==CURRENT_USER_VERSION
        objects={r[0]:(r[1],r[2]) for r in (await conn.execute(text("SELECT name,type,sql FROM sqlite_schema WHERE name LIKE 'trg_edges_%' OR name='ux_edges_one_mainline_per_parent'"))).all()}
        assert objects["ux_edges_one_mainline_per_parent"][0]=="index"
        assert normalize_sql(objects["ux_edges_one_mainline_per_parent"][1])==normalize_sql(INDEX_SQL)
        for name,sql in TRIGGERS.items():
            assert objects[name][0]=="trigger" and normalize_sql(objects[name][1])==normalize_sql(sql)
        assert (await conn.execute(text("PRAGMA integrity_check"))).scalar()=="ok"
        assert (await conn.execute(text("PRAGMA foreign_key_check"))).all()==[]
    await engine.dispose()


def test_option2_policy_is_exact_and_idempotent(tmp_path):
    asyncio.run(_option2_policy_is_exact_and_idempotent(tmp_path))


@pytest.mark.parametrize("failure",["injected","constraint"])
def test_option2_failure_rolls_back_demotion_and_version(tmp_path,failure,monkeypatch):
    async def run():
        engine=await _legacy_engine(tmp_path)
        if failure=="injected":monkeypatch.setenv("GROWTHMAP_TEST_FAIL_MIGRATION_AFTER_MAINLINE_DEMOTION","1")
        else:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE TRIGGER reject_option2 BEFORE UPDATE OF is_mainline ON edges WHEN OLD.id='a1' BEGIN SELECT RAISE(ABORT,'test constraint'); END"))
        with pytest.raises(Exception,match="injected|test constraint"):
            async with engine.begin() as conn:await migrate_sqlite(conn)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM edges WHERE id IN ('a1','a2') AND is_mainline=1"))).scalar()==2
            assert (await conn.execute(text("PRAGMA user_version"))).scalar()==CURRENT_USER_VERSION-1
            assert (await conn.execute(text("SELECT 1 FROM sqlite_schema WHERE name='ux_edges_one_mainline_per_parent'"))).first() is None
        await engine.dispose()
    asyncio.run(run())
