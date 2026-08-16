import asyncio, hashlib, os, shutil, sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from db.migrations import migrate_sqlite
from db.schema_contract import CURRENT_USER_VERSION

FIXTURE=Path('/mnt/c/ProgramData/GrowthMap-R15/gm-r15-2f0f607fa941/neutral.db')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def snapshot(path):
 c=sqlite3.connect(path)
 value=(c.execute('pragma user_version').fetchone()[0],c.execute("select group_concat(name||':'||type||':'||coalesce(sql,''),'|') from sqlite_schema order by name").fetchone()[0],{t:c.execute(f'select count(*),group_concat(id) from {t}').fetchone() for t in ('projects','branches','nodes','edges','content_blocks')})
 c.close();return value

async def migrate(path):
 e=create_async_engine(f'sqlite+aiosqlite:///{path}')
 try:
  async with e.begin() as c:await migrate_sqlite(c)
 finally:await e.dispose()

def copy_fixture(tmp_path):
 if not FIXTURE.exists():pytest.skip('preserved exact live fixture unavailable')
 p=tmp_path/'legacy.db';shutil.copyfile(FIXTURE,p);p.chmod(0o600);return p


def test_exact_live_legacy_timestamp_contract_preserves_custody(tmp_path):
 p=copy_fixture(tmp_path);before=sqlite3.connect(p)
 ids={t:[r[0] for r in before.execute(f'select id from {t} order by id')] for t in ('projects','branches','nodes','edges','content_blocks')}
 roots=before.execute('select id,root_node_id from projects order by id').fetchall(); links=before.execute('select id,branch_id from nodes order by id').fetchall();before.close()
 asyncio.run(migrate(p));c=sqlite3.connect(p)
 assert c.execute('pragma user_version').fetchone()[0]==CURRENT_USER_VERSION
 for t,cols in {'projects':('created_at','updated_at'),'nodes':('created_at','updated_at'),'edges':('created_at',),'content_blocks':('created_at','updated_at')}.items():
  info={r[1]:r for r in c.execute(f'pragma table_info({t})')};assert all(info[x][3] for x in cols);assert [r[0] for r in c.execute(f'select id from {t} order by id')]==ids[t]
 assert [r[0] for r in c.execute('select id from branches order by id')]==ids['branches']
 assert c.execute('select id,root_node_id from projects order by id').fetchall()==roots
 assert c.execute('select id,branch_id from nodes order by id').fetchall()==links
 assert c.execute('pragma integrity_check').fetchone()[0]=='ok' and c.execute('pragma foreign_key_check').fetchall()==[]
 assert c.execute("select count(*) from (select from_node_id from edges where relation_type='child_of' and is_mainline=1 group by from_node_id having count(*)>1)").fetchone()[0]==0
 assert c.execute("select count(*) from sqlite_schema where name like 'trg_edges_%' or name='ux_edges_one_mainline_per_parent'").fetchone()[0]==5;c.close()


def test_null_timestamp_fails_before_any_mutation(tmp_path):
 p=copy_fixture(tmp_path);c=sqlite3.connect(p);c.execute('update projects set created_at=null where id=(select id from projects limit 1)');c.commit();c.close();before=(digest(p),snapshot(p))
 with pytest.raises(RuntimeError,match='incompatible NULL data projects.created_at'):asyncio.run(migrate(p))
 assert (digest(p),snapshot(p))==before


@pytest.mark.parametrize('phase',['timestamp_ddl','additive_ddl','option2','objects'])
def test_each_phase_failure_is_logically_and_byte_atomic_and_retryable(tmp_path,monkeypatch,phase):
 p=copy_fixture(tmp_path);before=(digest(p),snapshot(p));monkeypatch.setenv('GROWTHMAP_TEST_FAIL_MIGRATION_PHASE',phase)
 with pytest.raises(RuntimeError,match='injected'):asyncio.run(migrate(p))
 assert (digest(p),snapshot(p))==before
 monkeypatch.delenv('GROWTHMAP_TEST_FAIL_MIGRATION_PHASE');asyncio.run(migrate(p))
 assert sqlite3.connect(p).execute('pragma user_version').fetchone()[0]==CURRENT_USER_VERSION
