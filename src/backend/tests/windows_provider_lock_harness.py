"""Standard-library native Windows gate for production provider_lock.

Run from a copied src/backend tree with Windows Python 3.12.  It injects only
minimal SQLAlchemy/database import stubs; lock and security primitives are the
production modules.
"""
import asyncio, os, pathlib, subprocess, sys, tempfile, types

base = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(base))
class URL:
    drivername = "sqlite+aiosqlite"
    def __init__(self, text): self.database = text.split("///", 1)[1]
engine = types.ModuleType("sqlalchemy.engine"); engine.make_url = URL
sqlalchemy = types.ModuleType("sqlalchemy"); sqlalchemy.engine = engine
database = types.ModuleType("db.database"); database.DATABASE_URL = ""
db = types.ModuleType("db"); db.database = database
sys.modules.update({"sqlalchemy": sqlalchemy, "sqlalchemy.engine": engine, "db": db, "db.database": database})
from api import provider_lock as lock
from api import windows_file_security as sec

fixture = pathlib.Path(os.environ["GM_LOCK_FIXTURE"])
dbfile = fixture / "db.sqlite"
lock.DATABASE_URL = f"sqlite+aiosqlite:///{dbfile}"

async def hold(provider, ready):
    async with lock.ProviderLock(provider, 3):
        pathlib.Path(ready).write_text("ready")
        await asyncio.sleep(30)

def child():
    asyncio.run(hold(sys.argv[2], sys.argv[3]))

def icacls(path, *args):
    subprocess.run(["icacls", str(path), *args], check=True, stdout=subprocess.DEVNULL)

def expect_unsafe(fn):
    try: fn()
    except (RuntimeError, OSError): return
    raise AssertionError("unsafe path accepted")

async def main():
    fixture.mkdir(); dbfile.write_bytes(b"db")
    # Production acceptance intentionally excludes WindowsPowerShell from PATH;
    # the policy runner must resolve the inbox executable from the native Windows
    # directory and successfully read owner/DACL metadata on every chain handle.
    os.environ["PATH"] = os.path.join(os.environ["SystemRoot"], "System32") + ";" + os.environ["SystemRoot"]
    powershell = sec._powershell_path()
    assert os.path.isabs(powershell) and os.path.basename(powershell).lower() == "powershell.exe"
    # End-to-end root/leaf creation and mandatory byte zero.
    async with lock.ProviderLock("new", 2): pass
    root = fixture / ".growthmap-locks"; leaf = next(root.glob("*.lock"))
    assert leaf.stat().st_size >= 1

    # Same leaf: real process contention/timeout then acquisition after release.
    ready = fixture / "ready"
    proc = subprocess.Popen([sys.executable, __file__, "child", "same", str(ready)], env=os.environ)
    while not ready.exists(): await asyncio.sleep(.02)
    try:
        try: await lock.ProviderLock("same", .15).__aenter__()
        except TimeoutError:
            assert sec._last_lock_error == 33  # real ERROR_LOCK_VIOLATION
        else: raise AssertionError("same leaf did not contend")
        # Different provider remains parallel.
        async with lock.ProviderLock("different", .3): pass
        waiter = asyncio.create_task(lock.ProviderLock("same", 3).__aenter__())
        await asyncio.sleep(.08); waiter.cancel()
        try: await waiter
        except asyncio.CancelledError: pass
        else: raise AssertionError("cancellation did not propagate")
    finally:
        proc.terminate(); proc.wait(timeout=5)
    async with lock.ProviderLock("same", .5): pass

    # Existing unsafe root and leaf are never repaired.
    icacls(root, "/grant", "*S-1-1-0:(OI)(CI)F")
    expect_unsafe(lambda: lock._open("bad-root"))
    icacls(root, "/remove", "*S-1-1-0")
    # restore exact private root for subsequent cells (test fixture only).
    sec.apply_private(root)
    fd = lock._open("bad-leaf"); lock._windows_fds.pop(fd); os.close(fd)
    badleaf = max(root.glob("*.lock"), key=lambda p:p.stat().st_mtime_ns)
    icacls(badleaf, "/grant", "*S-1-1-0:F")
    expect_unsafe(lambda: lock._open("bad-leaf"))

    # Root junction rejected; parent delete-child rejected before child creation.
    for p in root.iterdir(): p.unlink()
    root.rmdir(); target=fixture/"target"; target.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root), str(target)], check=True, stdout=subprocess.DEVNULL)
    expect_unsafe(lambda: lock._open("junction"))
    subprocess.run(["cmd", "/c", "rmdir", str(root)], check=True); target.rmdir()
    icacls(fixture, "/grant", "*S-1-1-0:(DC)")
    expect_unsafe(lambda: lock._open("parent")); assert not root.exists()
    icacls(fixture, "/remove", "*S-1-1-0")

    # Rebuild private root. A retained fd denies path replacement, and a leaf
    # reparse is rejected rather than followed.
    fd=lock._open("identity"); leafpath=lock._windows_fds[fd][2]
    replacement=fixture/"replacement"; replacement.write_bytes(b"x"); sec.apply_private(replacement)
    try:
        try: os.replace(replacement, leafpath)
        except PermissionError: pass
        else: raise AssertionError("open leaf was replaceable")
    finally: lock._windows_fds.pop(fd); os.close(fd)
    leafpath.unlink(); target=fixture/"leaf-target"; target.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(leafpath), str(target)], check=True, stdout=subprocess.DEVNULL)
    expect_unsafe(lambda: lock._open("identity"))
    subprocess.run(["cmd", "/c", "rmdir", str(leafpath)], check=True); target.rmdir()

    # Exact ABI exceptional conversion: injected CRT conversion failure closes
    # the original native HANDLE, proven invalid afterward.
    import ctypes, msvcrt
    probe=fixture/"conversion"; seen=[]; original_open=msvcrt.open_osfhandle
    def fail_open(handle, flags): seen.append(handle); raise RuntimeError("injected conversion")
    msvcrt.open_osfhandle=fail_open
    try: expect_unsafe(lambda: sec.open_leaf(probe))
    finally: msvcrt.open_osfhandle=original_open
    assert seen and not sec._kernel32().CloseHandle(sec.wintypes.HANDLE(seen[0]))
    assert ctypes.get_last_error() == 6  # ERROR_INVALID_HANDLE

    # Inject an exact WinAPI non-contention last-error at the production helper
    # boundary; access denied must propagate, never become False/timeout.
    fd=lock._open("error"); kernel=sec._kernel32(); original_lock=kernel.LockFileEx
    def fail_lock(*_): ctypes.set_last_error(5); return 0
    kernel.LockFileEx=fail_lock
    try:
        try: sec.lock_byte_zero(fd)
        except OSError as e: assert e.winerror == 5
        else: raise AssertionError("non-contention WinAPI error swallowed")
    finally:
        kernel.LockFileEx=original_lock; lock._windows_fds.pop(fd,None); os.close(fd)

    # Release precheck and post-unlock-check failures always remove map/close fd.
    async def release_failure(provider, post=False):
        held=lock.ProviderLock(provider,1); await held.__aenter__(); fd=held.fd
        original_check=lock._check_windows_fd; calls=0
        def fail_check(value):
            nonlocal calls; calls+=1
            if (not post and calls==1) or (post and calls==2): raise RuntimeError("injected check")
            return original_check(value)
        lock._check_windows_fd=fail_check
        try:
            try: await held.__aexit__()
            except RuntimeError: pass
            else: raise AssertionError("release check failure hidden")
        finally: lock._check_windows_fd=original_check
        assert fd not in lock._windows_fds
        try: os.fstat(fd)
        except OSError: pass
        else: raise AssertionError("release leaked fd")
        async with lock.ProviderLock(provider,.5): pass
    await release_failure("release-pre")
    await release_failure("release-post", True)

    # Successful native lock followed by postcheck failure: __aenter__ closes
    # the fd, clears the map, and the same provider can immediately acquire.
    original_check=lock._check_windows_fd; calls=0
    def fail_after_lock(fd):
        nonlocal calls; calls+=1
        if calls==2: raise RuntimeError("injected post-acquire check")
        return original_check(fd)
    lock._check_windows_fd=fail_after_lock
    failed=lock.ProviderLock("enter-post",.5)
    try:
        try: await failed.__aenter__()
        except RuntimeError: pass
        else: raise AssertionError("post-acquire failure hidden")
    finally: lock._check_windows_fd=original_check
    assert failed.fd is None
    async with lock.ProviderLock("enter-post",.5): pass
    print("WINDOWS_PROVIDER_LOCK_OK")

if __name__ == "__main__":
    if len(sys.argv)>1 and sys.argv[1]=="child": child()
    else: asyncio.run(main())
