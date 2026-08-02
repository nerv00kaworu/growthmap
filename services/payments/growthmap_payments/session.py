"""Fail-closed admin-session verification boundary."""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import os
import re
import stat
from typing import Protocol, final, runtime_checkable

_MAX_HASH_FILE = 1024
MAX_TOKEN_CHARS = 4096
_MAX_TOKEN_BYTES = 4096
ARGON2_MEMORY_MIN_KIB = 65536
ARGON2_MEMORY_MAX_KIB = 262144
ARGON2_ITERATIONS_MIN = 3
ARGON2_ITERATIONS_MAX = 6
ARGON2_PARALLELISM_MIN = 1
ARGON2_PARALLELISM_MAX = 4
_LOAD_ERROR = "admin session verifier unavailable"
_PHC = re.compile(
    rb"\$argon2id\$v=19\$m=([0-9]+),t=([0-9]+),p=([0-9]+)\$"
    rb"([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)"
)
_METADATA = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
             "st_size", "st_mtime_ns", "st_ctime_ns")


@runtime_checkable
class AdminSessionVerifier(Protocol):
    def verify(self, token: str) -> bool: ...


def _metadata(value: os.stat_result) -> tuple[int, ...]:
    return tuple(getattr(value, field) for field in _METADATA)


def _secure_regular(value: os.stat_result) -> bool:
    return (stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid() and
            value.st_nlink == 1 and value.st_mode & 0o077 == 0 and
            1 <= value.st_size <= _MAX_HASH_FILE)


def _canonical_decoded(value: bytes, minimum: int, maximum: int) -> bool:
    try:
        decoded = base64.b64decode(value + b"=" * (-len(value) % 4), validate=True)
        canonical = base64.b64encode(decoded).rstrip(b"=")
        return minimum <= len(decoded) <= maximum and canonical == value
    except Exception:
        return False


@final
class Argon2idSessionVerifier:
    """Verify one bounded bearer token against one safely loaded Argon2id PHC."""

    def __init__(self, *_args, **_kwargs):
        raise TypeError("use Argon2idSessionVerifier.from_hash_file")

    @classmethod
    def from_hash_file(cls, path: os.PathLike[str] | str) -> "Argon2idSessionVerifier":
        fd = None
        try:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            nonblock = getattr(os, "O_NONBLOCK", None)
            if (not isinstance(nofollow, int) or nofollow == 0 or
                    not isinstance(nonblock, int) or nonblock == 0):
                raise ValueError
            pathname = os.fspath(path)
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow | nonblock
            fd = os.open(pathname, flags)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError
            linked = os.lstat(pathname)
            if (not _secure_regular(opened) or stat.S_ISLNK(linked.st_mode) or
                    not _secure_regular(linked) or _metadata(opened) != _metadata(linked)):
                raise ValueError
            raw = b""
            while len(raw) <= _MAX_HASH_FILE:
                chunk = os.read(fd, _MAX_HASH_FILE + 1 - len(raw))
                if not chunk:
                    break
                raw += chunk
            reopened = os.fstat(fd)
            relinked = os.lstat(pathname)
            if (len(raw) != opened.st_size or len(raw) > _MAX_HASH_FILE or
                    not _secure_regular(reopened) or not _secure_regular(relinked) or
                    stat.S_ISLNK(relinked.st_mode) or
                    _metadata(reopened) != _metadata(opened) or
                    _metadata(relinked) != _metadata(opened)):
                raise ValueError
            raw.decode("ascii")
            match = _PHC.fullmatch(raw)
            if not match:
                raise ValueError
            numbers = match.group(1, 2, 3)
            if any(len(value) > 10 or not value.isdigit() for value in numbers):
                raise ValueError
            memory, iterations, parallelism = map(int, numbers)
            if not (ARGON2_MEMORY_MIN_KIB <= memory <= ARGON2_MEMORY_MAX_KIB and
                    ARGON2_ITERATIONS_MIN <= iterations <= ARGON2_ITERATIONS_MAX and
                    ARGON2_PARALLELISM_MIN <= parallelism <= ARGON2_PARALLELISM_MAX):
                raise ValueError
            if (not _canonical_decoded(match.group(4), 16, 64) or
                    not _canonical_decoded(match.group(5), 32, 64)):
                raise ValueError
            library_name = ctypes.util.find_library("argon2")
            if not library_name:
                raise ValueError
            library = ctypes.CDLL(library_name)
            verify = library.argon2id_verify
            verify.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
            verify.restype = ctypes.c_int
            instance = object.__new__(cls)
            instance._phc = raw
            instance._verify = verify
            return instance
        except Exception:
            raise RuntimeError(_LOAD_ERROR) from None
        finally:
            if fd is not None:
                os.close(fd)

    def verify(self, token: str) -> bool:
        try:
            if type(token) is not str or not token or len(token) > MAX_TOKEN_CHARS:
                return False
            raw = token.encode("utf-8", "strict")
            if len(raw) > _MAX_TOKEN_BYTES:
                return False
            buffer = ctypes.create_string_buffer(raw)
            return self._verify(self._phc, buffer, len(raw)) == 0
        except Exception:
            return False
