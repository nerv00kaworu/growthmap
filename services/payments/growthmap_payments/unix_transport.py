"""Bounded authenticated Unix-socket clients for private GrowthMap sidecars."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any

_MAX_REQUEST = 32_768
_MAX_RESPONSE = 32_768
_NONCE = re.compile(r"[A-Za-z0-9_-]{32,128}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class AuthenticatedUnixJSONClient:
    """One-request-per-connection client with transcript authentication.

    The shared transport key authenticates peer messages; operation-specific
    Ed25519 signatures remain the Authority/finality business evidence. The key
    is loaded only by this client boundary and never placed in requests/logs.
    """

    def __init__(self, socket_path: Path, transport_key_file: Path, *, service: str, timeout: float = 5.0):
        self.socket_path, self.transport_key_file = Path(socket_path), Path(transport_key_file)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,31}", service or ""):
            raise RuntimeError("unix transport service invalid")
        if type(timeout) not in (int, float) or isinstance(timeout, bool) or not 0.5 <= float(timeout) <= 20:
            raise RuntimeError("unix transport timeout invalid")
        self.service, self.timeout = service, float(timeout)
        self._key = self._load_key()

    def _load_key(self) -> bytes:
        try:
            meta = os.lstat(self.transport_key_file)
            if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) & 0o077:
                raise RuntimeError
            raw = self.transport_key_file.read_bytes()
        except Exception as exc:
            raise RuntimeError("unix transport key unavailable") from exc
        if len(raw) < 32 or len(raw) > 128:
            raise RuntimeError("unix transport key invalid")
        return raw

    def call(self, operation: str, arguments: dict[str, Any]) -> Any:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", operation or "") or type(arguments) is not dict:
            raise ValueError("unix transport request invalid")
        nonce = hashlib.sha256(os.urandom(32)).hexdigest()
        core = {"service": self.service, "operation": operation, "nonce": nonce, "arguments": arguments}
        request = {**core, "mac": hmac.new(self._key, b"growthmap-unix-request-v1\0" + _canonical(core), hashlib.sha256).hexdigest()}
        raw = _canonical(request) + b"\n"
        if len(raw) > _MAX_REQUEST:
            raise ValueError("unix transport request too large")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout); client.connect(str(self.socket_path)); client.sendall(raw); client.shutdown(socket.SHUT_WR)
                response = bytearray()
                while len(response) <= _MAX_RESPONSE:
                    chunk = client.recv(min(4096, _MAX_RESPONSE + 1 - len(response)))
                    if not chunk: break
                    response.extend(chunk)
        except (OSError, TimeoutError) as exc:
            raise RuntimeError("unix transport unavailable") from exc
        if not response or len(response) > _MAX_RESPONSE:
            raise RuntimeError("unix transport response invalid")
        try: document = json.loads(bytes(response).decode("utf-8", "strict"))
        except Exception as exc: raise RuntimeError("unix transport response invalid") from exc
        if type(document) is not dict or set(document) != {"service", "operation", "nonce", "ok", "result", "mac"}:
            raise RuntimeError("unix transport response invalid")
        core_response = {key: document[key] for key in ("service", "operation", "nonce", "ok", "result")}
        expected = hmac.new(self._key, b"growthmap-unix-response-v1\0" + _canonical(core_response), hashlib.sha256).hexdigest()
        if (document["service"] != self.service or document["operation"] != operation or document["nonce"] != nonce or
                type(document["ok"]) is not bool or type(document["mac"]) is not str or not hmac.compare_digest(document["mac"], expected)):
            raise RuntimeError("unix transport response authentication failed")
        if not document["ok"]:
            raise RuntimeError(f"{self.service} operation unavailable")
        return document["result"]


class UnixFinalityAuthenticator:
    def __init__(self, client: AuthenticatedUnixJSONClient): self.client = client
    def authenticate_finality_payload(self, payload: dict[str, Any]) -> bytes:
        result = self.client.call("sign_finality", {"payload": payload})
        if type(result) is not dict or set(result) != {"document"} or type(result["document"]) is not str:
            raise RuntimeError("finality sidecar response invalid")
        try: raw = result["document"].encode("utf-8", "strict")
        except UnicodeError as exc: raise RuntimeError("finality sidecar response invalid") from exc
        return raw


class UnixAuthorityClient:
    _OPERATIONS = frozenset({"handshake", "create_external_entitlement", "read_external_entitlement_acknowledgement", "revoke_external_entitlement", "read_external_revocation_acknowledgement"})
    def __init__(self, client: AuthenticatedUnixJSONClient): self.client = client
    def _call(self, operation: str, arguments: dict[str, Any]):
        if operation not in self._OPERATIONS: raise RuntimeError("Authority operation forbidden")
        return self.client.call(operation, arguments)
    def handshake(self): return self._call("handshake", {})
    def create_external_entitlement(self, **kwargs): return self._call("create_external_entitlement", kwargs)
    def read_external_entitlement_acknowledgement(self, **kwargs): return self._call("read_external_entitlement_acknowledgement", kwargs)
    def revoke_external_entitlement(self, **kwargs): return self._call("revoke_external_entitlement", kwargs)
    def read_external_revocation_acknowledgement(self, **kwargs): return self._call("read_external_revocation_acknowledgement", kwargs)
