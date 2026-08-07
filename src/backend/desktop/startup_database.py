"""Entitlement-bound desktop database verification before writable readiness."""
import hashlib, os, stat
from pathlib import Path
from sqlalchemy import text


def _digest(handle):
    handle.seek(0);digest=hashlib.sha256()
    while chunk:=handle.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def _path_matches(path, opened, meaningful):
    current=path.lstat()
    if path.is_symlink() or not stat.S_ISREG(current.st_mode) or current.st_nlink!=1:return False
    return not meaningful or (current.st_dev,current.st_ino)==(opened.st_dev,opened.st_ino)


async def _verify(engine,entitlement,expected,expected_size,meaningful,expected_identity,expected_quota,_test_after_hash=None,_test_after_connect=None,_test_before_quota=None):
    path=Path(engine.url.database);flags=os.O_RDONLY|getattr(os,"O_CLOEXEC",0)
    if os.name!="nt":flags|=getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags)
    try:
        with os.fdopen(fd,"rb",closefd=False) as handle:
            opened=os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1 or not _path_matches(path,opened,meaningful):raise RuntimeError("Desktop startup database identity mismatch")
            if meaningful and (opened.st_dev,opened.st_ino)!=expected_identity:raise RuntimeError("Desktop startup database identity mismatch")
            if opened.st_size!=expected_size or _digest(handle)!=expected:raise RuntimeError("Desktop startup database digest mismatch")
            if expected_quota!=entitlement.max_active_projects:raise RuntimeError("Desktop startup database quota evidence mismatch")
            if _test_after_hash:_test_after_hash(path)
            async with engine.connect() as connection:
                if _test_after_connect:_test_after_connect(path)
                if not _path_matches(path,opened,meaningful):raise RuntimeError("Desktop startup database identity mismatch")
                current=os.fstat(fd)
                if current.st_size!=expected_size or _digest(handle)!=expected:raise RuntimeError("Desktop startup database digest mismatch")
                # SQLite reports the connection's resolved main DB path. It is
                # advisory on Windows, but on POSIX must resolve to our target.
                sqlite_path=(await connection.execute(text("PRAGMA database_list"))).all()[0][2]
                if Path(sqlite_path).resolve()!=path.resolve():raise RuntimeError("Desktop startup connection database mismatch")
                if _test_before_quota:_test_before_quota(path)
                active=(await connection.execute(text("SELECT COUNT(*) FROM projects WHERE status='active'"))).scalar()
                if expected_quota is not None and active>expected_quota:raise RuntimeError("Desktop writable startup exceeds active project entitlement")
                final_active=(await connection.execute(text("SELECT COUNT(*) FROM projects WHERE status='active'"))).scalar()
                if final_active!=active:raise RuntimeError("Desktop startup database count changed during validation")
                # Final supported validation boundary: after every query, bind
                # pathname, held descriptor, bytes and the SQLite connection.
                if not _path_matches(path,opened,meaningful):raise RuntimeError("Desktop startup database identity mismatch")
                final_stat=path.lstat();current=os.fstat(fd)
                if current.st_size!=expected_size or final_stat.st_size!=expected_size or _digest(handle)!=expected:raise RuntimeError("Desktop startup database digest mismatch")
                with path.open("rb") as current_path:
                    if _digest(current_path)!=expected:raise RuntimeError("Desktop startup database digest mismatch")
    finally:
        os.close(fd)
    return {"sha256":expected,"size":expected_size,"identity":{"device":opened.st_dev,"inode":opened.st_ino,"meaningful":meaningful},"maxActiveProjects":expected_quota,"activeProjects":active}


async def verify_writable_startup(engine,entitlement,_test_after_hash=None,_test_after_connect=None,_test_before_quota=None):
    expected=os.getenv("GROWTHMAP_EXPECTED_DB_SHA256")
    if not expected:raise RuntimeError("Desktop writable startup requires database evidence")
    meaningful=os.getenv("GROWTHMAP_EXPECTED_DB_IDENTITY_MEANINGFUL")=="1"
    if not meaningful:raise RuntimeError("Desktop writable startup requires meaningful database identity")
    quota_text=os.environ["GROWTHMAP_EXPECTED_DB_MAX_ACTIVE_PROJECTS"];quota=None if quota_text=="unlimited" else int(quota_text)
    return await _verify(engine,entitlement,expected,int(os.environ["GROWTHMAP_EXPECTED_DB_SIZE"]),meaningful,(int(os.environ["GROWTHMAP_EXPECTED_DB_DEVICE"]),int(os.environ["GROWTHMAP_EXPECTED_DB_INODE"])),quota,_test_after_hash,_test_after_connect,_test_before_quota)


async def verify_fresh_created(engine,entitlement,created_identity,_test_before_baseline=None,_test_after_capture=None):
    path=Path(engine.url.database)
    if _test_before_baseline:_test_before_baseline(path)
    stat_value=path.lstat();meaningful=created_identity["meaningful"]
    # POSIX binds creation to the exact inode. On Windows, where dev/inode may
    # be unavailable, regular/link/digest/size is a weaker fallback; a byte-identical
    # replacement may be indistinguishable.
    if meaningful and (stat_value.st_dev,stat_value.st_ino)!=(created_identity["device"],created_identity["inode"]):raise RuntimeError("Fresh desktop database creation identity mismatch")
    with path.open("rb") as handle:data=handle.read()
    return await _verify(engine,entitlement,hashlib.sha256(data).hexdigest(),len(data),meaningful,(stat_value.st_dev,stat_value.st_ino),entitlement.max_active_projects,_test_after_capture)
