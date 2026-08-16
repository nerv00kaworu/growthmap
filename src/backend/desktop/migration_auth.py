"""HMAC-bound, one-launch authorization for desktop schema migration."""
import hashlib, hmac, json, os, re
from datetime import datetime
from pathlib import Path

_BACKUP = re.compile(r"(?:backup|rollback)-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-\d{3}Z-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.db", re.I)
_MARKER_KEYS = ("schemaVersion", "kind", "backupId", "sha256", "size", "projects", "fromVersion", "toVersion", "createdAt")
_MANIFEST_KEYS = ("format", "createdAt", "file", "size", "projects", "sha256", "durability")


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def _durability(value):
    return value == {"fileFsync": True, "directoryFsync": True} or value == {"fileFlush": "FlushFileBuffers", "directoryFlush": "unsupported-windows-best-effort"}


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_nlink)


def _stable_bytes(path, limit=None):
    # Windows CRT defaults low-level descriptors to text mode. SQLite commonly
    # contains 0x1a, which text-mode os.read treats as EOF and would make a valid
    # Electron-verified backup fail its independent backend hash verification.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not __import__("stat").S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("managed evidence is not a single-link regular file")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if limit is not None and total > limit:
                raise OSError("managed evidence is too large")
            chunks.append(chunk)
        after = os.fstat(fd)
        linked = path.lstat()
        if path.is_symlink() or not path.is_file() or linked.st_nlink != 1 or _identity(before) != _identity(after) or _identity(after) != _identity(linked):
            raise OSError("managed evidence changed while validating")
        return b"".join(chunks), after
    finally:
        os.close(fd)


def _canonical_marker(doc):
    # Node JSON.stringify inserts these keys in this exact order with compact UTF-8 JSON.
    return json.dumps({key: doc[key] for key in _MARKER_KEYS}, separators=(",", ":"), ensure_ascii=False)


def authorized() -> bool:
    key = os.getenv("GROWTHMAP_SESSION_TOKEN", "").encode()
    mac = os.getenv("GROWTHMAP_MIGRATION_MARKER_MAC", "")
    marker = os.getenv("GROWTHMAP_MIGRATION_MARKER_FILE", "")
    if not key or not re.fullmatch(r"[0-9a-f]{64}", mac) or not marker:
        return False
    try:
        user_data = Path(os.environ["GROWTHMAP_LICENSE_FILE"]).resolve().parent
        marker_path = Path(marker).resolve()
        if marker_path != user_data / "migration-authorization.json":
            return False
        raw, _ = _stable_bytes(marker_path, 1024 * 1024)
        doc = json.loads(raw)
        if not isinstance(doc, dict) or tuple(doc) != _MARKER_KEYS:
            return False
        canonical = _canonical_marker(doc)
        if not hmac.compare_digest(hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest(), mac):
            return False
        backup_id = doc["backupId"]
        if doc["schemaVersion"] != 1 or doc["kind"] != "pre-migration-backup" or not isinstance(backup_id, str) or not _BACKUP.fullmatch(backup_id):
            return False
        if not isinstance(doc["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", doc["sha256"]):
            return False
        if not _integer(doc["size"]) or doc["size"] < 100 or not _integer(doc["projects"]) or doc["projects"] < 0 or not _timestamp(doc["createdAt"]):
            return False
        if not isinstance(doc["fromVersion"], str) or not isinstance(doc["toVersion"], str):
            return False
        backups = (user_data / "backups").resolve()
        backup = backups / backup_id
        manifest = Path(str(backup) + ".json")
        if backup.resolve().parent != backups:
            return False
        manifest_raw, _ = _stable_bytes(manifest, 1024 * 1024)
        meta = json.loads(manifest_raw)
        if not isinstance(meta, dict) or set(meta) != set(_MANIFEST_KEYS):
            return False
        if meta["format"] != "growthmap-backup-v1" or meta["file"] != backup_id or not _BACKUP.fullmatch(meta["file"]) or not _timestamp(meta["createdAt"]) or not _durability(meta["durability"]):
            return False
        if meta["size"] != doc["size"] or meta["projects"] != doc["projects"] or meta["sha256"] != doc["sha256"]:
            return False
        backup_raw, backup_stat = _stable_bytes(backup)
        if backup_stat.st_size != doc["size"] or hashlib.sha256(backup_raw).hexdigest() != doc["sha256"]:
            return False
        # Consume only after the final marker, manifest and database identity/hash checks.
        marker_path.unlink()
        if os.name != "nt":
            directory = os.open(user_data, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return True
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
