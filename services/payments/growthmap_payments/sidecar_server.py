"""Fail-closed authenticated Unix sidecar servers for finality and Authority."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import stat
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Protocol

from .finality import _FIELDS as FINALITY_FIELDS, _SIGNED_DOMAIN, canonical_payload

_MAX_REQUEST = 32_768
_MAX_RESPONSE = 32_768
_NONCE = re.compile(r"[a-f0-9]{64}")
_MAC = re.compile(r"[a-f0-9]{64}")
_OPERATION = re.compile(r"[a-z][a-z0-9_.-]{2,63}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class SidecarSigner(Protocol):
    def sign(self, message: bytes) -> bytes: ...


class ReplayWindow:
    """Bounded process window; clients also use one connection and fresh randomness."""
    def __init__(self, maximum: int = 4096):
        if type(maximum) is not int or not 128 <= maximum <= 65_536: raise RuntimeError("sidecar replay window invalid")
        self.maximum, self._values, self._lock = maximum, OrderedDict(), threading.Lock()
    def consume(self, nonce: str) -> None:
        with self._lock:
            if nonce in self._values: raise ValueError("sidecar request replayed")
            self._values[nonce] = None
            if len(self._values) > self.maximum: self._values.popitem(last=False)


class FinalityHandler:
    operations = frozenset({"sign_finality"})
    def __init__(self, signer: SidecarSigner): self.signer = signer
    def dispatch(self, operation: str, arguments: dict[str, Any]) -> Any:
        if operation != "sign_finality" or type(arguments) is not dict or set(arguments) != {"payload"}:
            raise ValueError("finality operation forbidden")
        payload = arguments["payload"]
        if type(payload) is not dict or set(payload) != FINALITY_FIELDS:
            raise ValueError("finality payload invalid")
        raw = canonical_payload(payload)
        if len(raw) > 16_000: raise ValueError("finality payload too large")
        signature = self.signer.sign(_SIGNED_DOMAIN + raw)
        if type(signature) is not bytes or len(signature) != 64: raise RuntimeError("finality signing unavailable")
        return {"document": _canonical({"signature": base64.b64encode(signature).decode(), "payload": payload}).decode()}


class AuthorityHandler:
    operations = frozenset({"handshake", "create_external_entitlement", "read_external_entitlement_acknowledgement", "revoke_external_entitlement", "read_external_revocation_acknowledgement"})
    def __init__(self, authority: Any): self.authority = authority
    def dispatch(self, operation: str, arguments: dict[str, Any]) -> Any:
        if operation not in self.operations or type(arguments) is not dict: raise ValueError("Authority operation forbidden")
        if operation == "handshake":
            if arguments: raise ValueError("Authority arguments invalid")
            return self.authority.handshake()
        method = getattr(self.authority, operation, None)
        if not callable(method): raise RuntimeError("Authority operation unavailable")
        return method(**arguments)


class AuthenticatedUnixSidecarServer:
    """Authenticated AF_UNIX server; business results never expose exceptions."""
    def __init__(self, socket_path: Path, transport_key_file: Path, *, service: str, handler: Any,
                 expected_peer_uid: int, timeout: float = 5.0, replay_window: ReplayWindow | None = None):
        self.socket_path, self.transport_key_file = Path(socket_path), Path(transport_key_file)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,31}", service or ""): raise RuntimeError("sidecar service invalid")
        if type(expected_peer_uid) is not int or expected_peer_uid < 0: raise RuntimeError("sidecar peer uid invalid")
        if type(timeout) not in (int,float) or isinstance(timeout,bool) or not .5 <= float(timeout) <= 20: raise RuntimeError("sidecar timeout invalid")
        self.service, self.handler, self.expected_peer_uid, self.timeout = service, handler, expected_peer_uid, float(timeout)
        self.replay_window, self._key, self._socket = replay_window or ReplayWindow(), self._load_key(), None

    def _load_key(self) -> bytes:
        try:
            meta=os.lstat(self.transport_key_file)
            if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode)&0o077: raise RuntimeError
            raw=self.transport_key_file.read_bytes()
        except Exception as exc: raise RuntimeError("sidecar transport key unavailable") from exc
        if not 32 <= len(raw) <= 128: raise RuntimeError("sidecar transport key invalid")
        return raw

    def bind(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists() or self.socket_path.is_symlink(): raise RuntimeError("sidecar socket path already exists")
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); server.settimeout(self.timeout)
        try:
            server.bind(str(self.socket_path)); os.chmod(self.socket_path,0o600); server.listen(16); self._socket=server
        except Exception:
            server.close()
            if self.socket_path.exists(): self.socket_path.unlink()
            raise

    def close(self) -> None:
        if self._socket is not None: self._socket.close(); self._socket=None
        try:
            if self.socket_path.is_socket(): self.socket_path.unlink()
        except OSError: pass

    def serve_once(self) -> None:
        if self._socket is None: raise RuntimeError("sidecar not bound")
        connection,_=self._socket.accept()
        with connection:
            connection.settimeout(self.timeout)
            if hasattr(socket,"SO_PEERCRED"):
                _,uid,_=struct.unpack("3i",connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))
                if uid != self.expected_peer_uid: return
            raw=bytearray()
            try:
                while len(raw)<=_MAX_REQUEST:
                    chunk=connection.recv(min(4096,_MAX_REQUEST+1-len(raw)))
                    if not chunk: break
                    raw.extend(chunk)
                if not raw or len(raw)>_MAX_REQUEST: return
                request=json.loads(bytes(raw).decode("utf-8","strict"))
                operation,nonce=self._authenticate_request(request); self.replay_window.consume(nonce)
                result=self.handler.dispatch(operation,request["arguments"]); response=self._response(operation,nonce,True,result)
            except Exception:
                operation=request.get("operation","invalid") if type(locals().get("request")) is dict else "invalid"
                nonce=request.get("nonce","0"*64) if type(locals().get("request")) is dict else "0"*64
                response=self._response(operation if _OPERATION.fullmatch(operation or "") else "invalid",nonce if _NONCE.fullmatch(nonce or "") else "0"*64,False,None)
            if len(response)<=_MAX_RESPONSE: connection.sendall(response)

    def _authenticate_request(self, request: Any) -> tuple[str,str]:
        if type(request) is not dict or set(request)!={"service","operation","nonce","arguments","mac"}: raise ValueError
        operation,nonce=request["operation"],request["nonce"]
        if request["service"]!=self.service or type(operation) is not str or not _OPERATION.fullmatch(operation) or operation not in self.handler.operations or type(nonce) is not str or not _NONCE.fullmatch(nonce) or type(request["arguments"]) is not dict or type(request["mac"]) is not str or not _MAC.fullmatch(request["mac"]): raise ValueError
        core={k:request[k] for k in ("service","operation","nonce","arguments")}; expected=hmac.new(self._key,b"growthmap-unix-request-v1\0"+_canonical(core),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request["mac"],expected): raise ValueError
        return operation,nonce

    def _response(self,operation:str,nonce:str,ok:bool,result:Any)->bytes:
        core={"service":self.service,"operation":operation,"nonce":nonce,"ok":ok,"result":result}; mac=hmac.new(self._key,b"growthmap-unix-response-v1\0"+_canonical(core),hashlib.sha256).hexdigest(); return _canonical({**core,"mac":mac})
