"""Canonical, cancellation-safe cross-process provider lock."""
import asyncio, concurrent.futures, hashlib, os, secrets, stat
from pathlib import Path
from urllib.parse import unquote
from sqlalchemy.engine import make_url
from db.database import DATABASE_URL


def canonical_database_file(url_text: str | None = None) -> tuple[Path, tuple[int, int]]:
    url = make_url(url_text or DATABASE_URL)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise RuntimeError("provider secret recovery requires a local SQLite file")
    raw = unquote(url.database)
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("database is not a regular file")
    return path, (int(info.st_dev), int(info.st_ino))


def _remove_owned_staging(staging: Path, staging_identity, security) -> None:
    """Remove only the still-private directory instance created by this process."""
    try:
        actual = security.verify(staging, kind="dir")
    except FileNotFoundError:
        return
    if actual != staging_identity:
        raise RuntimeError("provider lock staging directory replaced")
    try:
        staging.rmdir()
    except FileNotFoundError:
        return


def _verified_root(db: Path) -> tuple[Path, object]:
    root = db.parent / ".growthmap-locks"
    if os.name == "nt":
        from api import windows_file_security as security
        parent_identity = security.verify(db.parent, kind="dir", container=True)
        try:
            root.lstat()
        except FileNotFoundError:
            # Never publish the transient inherited ACL. Build an unpredictable,
            # exact-private sibling first, then atomically publish without replace.
            staging = db.parent / (".growthmap-locks.init-" + secrets.token_hex(16))
            staging.mkdir(mode=0o700)
            staging_identity = None
            try:
                security.apply_private(staging)
                staging_identity, parent_before_publish = security.verify_many([
                    (staging, "dir", False), (db.parent, "dir", True)])
                if parent_before_publish != parent_identity:
                    raise RuntimeError("provider lock parent replaced during initialization")
                try:
                    os.rename(staging, root)  # Windows rename is no-replace.
                    staging_identity = None  # Published; never clean by staging path.
                except FileExistsError:
                    _remove_owned_staging(staging, staging_identity, security)
                    staging_identity = None
            finally:
                if staging_identity is not None:
                    _remove_owned_staging(staging, staging_identity, security)
        root_identity, parent_after = security.verify_many([
            (root, "dir", False), (db.parent, "dir", True)])
        if parent_after != parent_identity:
            raise RuntimeError("provider lock parent replaced")
        return root, root_identity

    if root.exists() or root.is_symlink():
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("unsafe provider lock root")
    else:
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = root.lstat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RuntimeError("provider lock root is not private")
    return root, (int(info.st_dev), int(info.st_ino))


def _verify_windows_open(root: Path, root_identity, path: Path, fd: int):
    from api import windows_file_security as security
    actual_root, path_identity = security.verify_many([
        (root, "dir", False), (path, "file", False)])
    if actual_root != root_identity:
        raise RuntimeError("provider lock root replaced")
    volume, file_id, links = security.handle_identity(fd)
    if links != 1 or path_identity != (volume, file_id):
        raise RuntimeError("provider lock path/handle mismatch")
    return path_identity


def _open(provider_id: str):
    db, identity = canonical_database_file()
    root, root_identity = _verified_root(db)
    name = hashlib.sha256(f"{identity[0]}:{identity[1]}:{provider_id}".encode()).hexdigest() + ".lock"
    path = root / name
    if os.name == "nt":
        from api import windows_file_security as security
        fd, created = security.open_leaf(path)
        try:
            if created:
                security.apply_private(path)
            leaf_identity = _verify_windows_open(root, root_identity, path, fd)
            if os.fstat(fd).st_size < 1:
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, b"\0")
                os.fsync(fd)
            # Store identities by fd: the no-delete-share handle prevents replacement,
            # while these values make acquisition/release checks explicit and visible.
            _windows_fds[fd] = (root, root_identity, path, leaf_identity)
            return fd
        except BaseException:
            os.close(fd)
            raise

    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077
            or info.st_uid != os.geteuid()):
        os.close(fd)
        raise RuntimeError("unsafe provider lock")
    return fd


_windows_fds: dict[int, tuple] = {}


def _check_windows_fd(fd: int) -> None:
    if fd not in _windows_fds:
        raise RuntimeError("untracked Windows provider-lock handle")
    root, root_identity, path, leaf_identity = _windows_fds[fd]
    if _verify_windows_open(root, root_identity, path, fd) != leaf_identity:
        raise RuntimeError("provider lock leaf replaced")


def _try(fd: int) -> bool:
    if os.name == "nt":
        from api import windows_file_security as security
        _check_windows_fd(fd)
        if not security.lock_byte_zero(fd):
            return False
        _check_windows_fd(fd)
        return True
    os.lseek(fd, 0, os.SEEK_SET)
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _release(fd: int):
    try:
        if os.name == "nt":
            from api import windows_file_security as security
            _check_windows_fd(fd)
            security.unlock_byte_zero(fd)
            _check_windows_fd(fd)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        _windows_fds.pop(fd, None)
        os.close(fd)


_native_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="provider-custody")


def _submit_worker(function, *args):
    """Return the raw ownership future; no cancellable asyncio wrapper owns it."""
    return _native_executor.submit(function, *args)


async def _reap_worker(worker: concurrent.futures.Future):
    """Non-blockingly reap the actual native-thread completion primitive."""
    current = asyncio.current_task();cancelled = 0
    while not worker.done():
        try:
            await asyncio.sleep(.005)
        except asyncio.CancelledError:
            cancelled += 1
            if current is not None:current.uncancel()
    try:return worker.result(),cancelled,None
    except BaseException as exc:return None,cancelled,exc


def _abandon_unstarted_release(fd: int) -> None:
    """A cancelled raw future proves _release never started; close ownership."""
    _windows_fds.pop(fd, None)
    os.close(fd)


def _raise_cancelled(count: int, cause: BaseException | None = None):
    if not count:
        if cause is not None: raise cause
        return
    current = asyncio.current_task()
    if current is not None:
        for _ in range(count): current.cancel()
    error = asyncio.CancelledError()
    if cause is not None: raise error from cause
    raise error


class ProviderLock:
    def __init__(self, provider_id: str, timeout=10.0):
        self.provider_id = provider_id
        self.timeout = timeout
        self.fd = None

    async def __aenter__(self):
        # Native Windows custody verification invokes PowerShell and may take
        # seconds on a loaded runner. Never block the event loop: cancellation
        # must be able to release a contended lock while verification runs.
        opening = _submit_worker(_open, self.provider_id)
        fd, cancelled, worker_error = await _reap_worker(opening)
        if cancelled:
            if fd is not None:
                _windows_fds.pop(fd, None)
                os.close(fd)
            _raise_cancelled(cancelled, worker_error)
        _raise_cancelled(0, worker_error)
        self.fd = fd
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        try:
            while True:
                trying = _submit_worker(_try, self.fd)
                acquired, cancelled, worker_error = await _reap_worker(trying)
                if cancelled:
                    # The worker has settled, so outer cleanup may now safely
                    # release/close even if it acquired the lock.
                    _raise_cancelled(cancelled, worker_error)
                _raise_cancelled(0, worker_error)
                if acquired: break
                if loop.time() >= deadline:
                    raise TimeoutError("provider lock timed out")
                await asyncio.sleep(.025)
            return self
        except BaseException:
            _windows_fds.pop(self.fd, None)
            os.close(self.fd)
            self.fd = None
            raise

    async def __aexit__(self, *_):
        if self.fd is not None:
            releasing = _submit_worker(_release, self.fd)
            try:
                _, cancelled, worker_error = await _reap_worker(releasing)
                if releasing.cancelled():
                    _abandon_unstarted_release(self.fd)
            finally:
                self.fd = None
            if cancelled: _raise_cancelled(cancelled, worker_error)
            _raise_cancelled(0, worker_error)
