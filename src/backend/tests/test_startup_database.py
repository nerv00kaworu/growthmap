import asyncio,hashlib,os,sqlite3
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


def active_projects(path):
 with sqlite3.connect(path) as connection:return connection.execute("SELECT COUNT(*) FROM projects WHERE status='active'").fetchone()[0]


@pytest.mark.parametrize('phase',['after_hash','after_connect'])
def test_path_replacement_before_readiness_fails(tmp_path,monkeypatch,phase):
 path=tmp_path/'db.sqlite';fixture(path);original=path.read_bytes();env(monkeypatch,path);engine=create_async_engine(f'sqlite+aiosqlite:///{path}');proof=None;outcome=None
 def inject(target):
  nonlocal outcome
  try:swap(target)
  except PermissionError:outcome='denied';raise
  outcome='replaced'
 kwargs={f'_test_{phase}':inject}
 try:
  try:proof=asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1),**kwargs))
  except PermissionError:assert outcome=='denied'
  except RuntimeError as error:assert outcome=='replaced' and 'identity mismatch' in str(error)
  else:pytest.fail('replacement injection returned writable startup proof')
 finally:
  asyncio.run(engine.dispose());path.with_suffix('.swap').unlink(missing_ok=True)
 assert proof is None and path.read_bytes()==original and active_projects(path)==1


def test_missing_writable_evidence_fails(tmp_path,monkeypatch):
 path=tmp_path/'db.sqlite';fixture(path);engine=create_async_engine(f'sqlite+aiosqlite:///{path}');monkeypatch.delenv('GROWTHMAP_EXPECTED_DB_SHA256',raising=False)
 with pytest.raises(RuntimeError,match='requires database evidence'):asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1)))
 asyncio.run(engine.dispose())


def test_late_replacement_before_quota_query_is_rejected_by_final_boundary(tmp_path,monkeypatch):
 path=tmp_path/'db.sqlite';fixture(path);original=path.read_bytes();env(monkeypatch,path);engine=create_async_engine(f'sqlite+aiosqlite:///{path}');proof=None;outcome=None
 def replace_with_overquota(target):
  nonlocal outcome
  replacement=target.with_suffix('.replacement');replacement.write_bytes(target.read_bytes())
  with sqlite3.connect(replacement) as connection:connection.execute("insert into projects values('p2','second','','',NULL,'active','{}','','')")
  try:os.replace(replacement,target)
  except PermissionError:outcome='denied';raise
  outcome='replaced'
 try:
  try:proof=asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1),_test_before_quota=replace_with_overquota))
  except PermissionError:assert outcome=='denied'
  except RuntimeError as error:assert outcome=='replaced' and ('identity mismatch' in str(error) or 'digest mismatch' in str(error))
  else:pytest.fail('replacement injection returned writable startup proof')
 finally:
  asyncio.run(engine.dispose());path.write_bytes(original);path.with_suffix('.replacement').unlink(missing_ok=True)
 assert proof is None and path.read_bytes()==original and active_projects(path)==1


def test_normal_proof_reports_final_identity_digest_and_active_count(tmp_path,monkeypatch):
 path=tmp_path/'db.sqlite';fixture(path);env(monkeypatch,path);engine=create_async_engine(f'sqlite+aiosqlite:///{path}')
 proof=asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1)));assert proof['activeProjects']==1 and proof['sha256'] and proof['identity']
 asyncio.run(engine.dispose())


def test_authoritative_quota_and_unlimited(tmp_path,monkeypatch):
 path=tmp_path/'db.sqlite';fixture(path);env(monkeypatch,path,'1');engine=create_async_engine(f'sqlite+aiosqlite:///{path}')
 asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=1)))
 with pytest.raises(RuntimeError,match='quota evidence mismatch'):asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=None)))
 env(monkeypatch,path,'unlimited');asyncio.run(verify_writable_startup(engine,SimpleNamespace(max_active_projects=None)));asyncio.run(engine.dispose())
