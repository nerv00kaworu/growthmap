import asyncio,os,sqlite3
from types import SimpleNamespace
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from desktop.startup_database import verify_fresh_created
from tests.test_database_maintenance import fixture


async def create(engine,path):
 fixture(path)


def test_fresh_created_database_is_proven_before_readiness(tmp_path):
 path=tmp_path/'fresh.db';engine=create_async_engine(f'sqlite+aiosqlite:///{path}');asyncio.run(create(engine,path))
 proof=asyncio.run(verify_fresh_created(engine,SimpleNamespace(max_active_projects=1)))
 assert proof['maxActiveProjects']==1 and proof['sha256'] and proof['identity']
 asyncio.run(engine.dispose())

@pytest.mark.parametrize('kind',['replace','overquota'])
def test_fresh_mutation_before_readiness_fails(tmp_path,kind):
 path=tmp_path/'fresh.db';engine=create_async_engine(f'sqlite+aiosqlite:///{path}');asyncio.run(create(engine,path))
 def inject(target):
  if kind=='replace':
   other=target.with_suffix('.swap');other.write_bytes(target.read_bytes());os.replace(other,target)
  else:
   connection=sqlite3.connect(target);connection.execute("insert into projects(id,name,status,created_at,updated_at) values('p2','second','active','','')");connection.execute("insert into projects(id,name,status,created_at,updated_at) values('p3','third','active','','')");connection.commit();connection.close()
 with pytest.raises(RuntimeError,match='identity mismatch|digest mismatch|exceeds active project entitlement'):asyncio.run(verify_fresh_created(engine,SimpleNamespace(max_active_projects=1),inject))
 asyncio.run(engine.dispose())
