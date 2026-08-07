import asyncio,hashlib,os
from types import SimpleNamespace
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from desktop.startup_database import verify_writable_startup
from tests.test_database_maintenance import fixture


def env(monkeypatch,path,quota='1'):
 stat=path.stat();data=path.read_bytes()
 values={'GROWTHMAP_EXPECTED_DB_DEVICE':str(stat.st_dev),'GROWTHMAP_EXPECTED_DB_INODE':str(stat.st_ino),'GROWTHMAP_EXPECTED_DB_IDENTITY_MEANINGFUL':'1' if stat.st_dev or stat.st_ino else '0','GROWTHMAP_EXPECTED_DB_SHA256':hashlib.sha256(data).hexdigest(),'GROWTHMAP_EXPECTED_DB_SIZE':str(len(data)),'GROWTHMAP_EXPECTED_DB_MAX_ACTIVE_PROJECTS':quota}
 for k,v in values.items():monkeypatch.setenv(k,v)


def swap(path):
 other=path.with_suffix('.swap');other.write_bytes(path.read_bytes());os.replace(other,path)

@pytest.mark.parametrize('phase',['after_hash','after_connect'])
def test_path_replacement_before_readiness_fails(tmp_path,monkeypatch,phase):
 path=tmp_path/'db.sqlite';fixture(path);env(monkeypatch,path);engine=create_async_engine(f'sqlite+aiosqlite:///{path}')
 kwargs={f'_test_{phase}':swap}
 with pytest.raises(RuntimeError,match='identity mismatch'):asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1),**kwargs))
 asyncio.run(engine.dispose())


def test_authoritative_quota_and_unlimited(tmp_path,monkeypatch):
 path=tmp_path/'db.sqlite';fixture(path);env(monkeypatch,path,'1');engine=create_async_engine(f'sqlite+aiosqlite:///{path}')
 asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1)))
 with pytest.raises(RuntimeError,match='quota evidence mismatch'):asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=None)))
 env(monkeypatch,path,'unlimited');asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=None)));asyncio.run(engine.dispose())
