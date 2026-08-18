"""Canonical, cancellation-safe cross-process provider lock."""
import asyncio, hashlib, os, stat
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


def _verified_root(db: Path) -> tuple[Path, object]:
    root = db.parent / ".growthmap-locks"
    if os.name == "nt":
        from api import windows_file_security as security
        parent_identity = security.verify(db.parent, kind="dir", container=True)
        try:
            root.lstat()
        except FileNotFoundError:
            try:
                root.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise RuntimeError("provider lock root initialization raced") from exc
            try:
                security.apply_private(root)
            except BaseException:
                # Deliberately leave a fail-closed existing artifact; never auto-repair it.
                raise
            if security.verify(db.parent, kind="dir", container=True) != parent_identity:
                raise RuntimeError("provider lock parent replaced during initialization")
        root_identity = security.verify(root, kind="dir")
        if security.verify(db.parent, kind="dir", container=True) != parent_identity:
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
    if security.verify(root, kind="dir") != root_identity:
        raise RuntimeError("provider lock root replaced")
    path_identity = security.verify(path, kind="file")
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


class ProviderLock:
    def __init__(self, provider_id: str, timeout=10.0):
        self.provider_id = provider_id
        self.timeout = timeout
        self.fd = None

    async def __aenter__(self):
        self.fd = _open(self.provider_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        try:
            while not _try(self.fd):
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
            try:
                _release(self.fd)
            finally:
                self.fd = None
