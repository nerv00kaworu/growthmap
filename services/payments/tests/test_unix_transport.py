"""Private sidecar Unix transport transcript and boundary tests."""
import hashlib
import hmac
import json
import os
import socket
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="production sidecars use Linux AF_UNIX and POSIX key modes")

from growthmap_payments.unix_transport import AuthenticatedUnixJSONClient, UnixAuthorityClient, UnixFinalityAuthenticator

KEY = b"isolated-unix-transport-key-32bytes-minimum"


def canonical(v): return json.dumps(v, sort_keys=True, separators=(",", ":")).encode()


def keyfile(tmp_path):
    path = tmp_path / "transport.key"; path.write_bytes(KEY); path.chmod(0o600); return path


def serve_once(path: Path, handler):
    ready = threading.Event()
    def run():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path)); server.listen(1); ready.set()
            conn, _ = server.accept()
            with conn:
                raw = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk: break
                    raw += chunk
                conn.sendall(handler(json.loads(raw)))
    thread = threading.Thread(target=run); thread.start(); ready.wait(2); return thread


def response(req, result, *, key=KEY, mutate=None):
    core = {"service": req["service"], "operation": req["operation"], "nonce": req["nonce"], "ok": True, "result": result}
    if mutate: core.update(mutate)
    return canonical({**core, "mac": hmac.new(key, b"growthmap-unix-response-v1\0" + canonical(core), hashlib.sha256).hexdigest()})


def test_authenticated_roundtrip_and_finality_document(tmp_path):
    socket_path = tmp_path / "finality.sock"
    def handler(req):
        core = {k:req[k] for k in ("service","operation","nonce","arguments")}
        expected = hmac.new(KEY, b"growthmap-unix-request-v1\0" + canonical(core), hashlib.sha256).hexdigest()
        assert req["mac"] == expected and req["operation"] == "sign_finality"
        return response(req, {"document": '{"payload":{},"signature":"fixture"}'})
    thread = serve_once(socket_path, handler)
    client = AuthenticatedUnixJSONClient(socket_path, keyfile(tmp_path), service="finality")
    assert UnixFinalityAuthenticator(client).authenticate_finality_payload({"x": 1}).startswith(b'{"payload"')
    thread.join(2); assert not thread.is_alive()


def test_wrong_mac_nonce_service_and_negative_response_fail_closed(tmp_path):
    for index, change in enumerate((
        {"bad_key": True}, {"mutate": {"nonce": "0" * 64}}, {"mutate": {"service": "other"}}, {"ok": False},
    )):
        socket_path = tmp_path / f"bad-{index}.sock"
        def handler(req, change=change):
            if change.get("ok") is False:
                core={"service":req["service"],"operation":req["operation"],"nonce":req["nonce"],"ok":False,"result":None}
                return canonical({**core,"mac":hmac.new(KEY,b"growthmap-unix-response-v1\0"+canonical(core),hashlib.sha256).hexdigest()})
            return response(req, {}, key=b"x"*32 if change.get("bad_key") else KEY, mutate=change.get("mutate"))
        thread=serve_once(socket_path,handler); client=AuthenticatedUnixJSONClient(socket_path,keyfile(tmp_path),service="authority")
        with pytest.raises(RuntimeError, match="authentication failed|operation unavailable"):
            client.call("handshake",{})
        thread.join(2)


def test_key_permissions_request_bounds_and_authority_allowlist(tmp_path):
    key = keyfile(tmp_path); key.chmod(0o644)
    with pytest.raises(RuntimeError, match="key unavailable"):
        AuthenticatedUnixJSONClient(tmp_path/"none.sock", key, service="authority")
    key.chmod(0o600); client=AuthenticatedUnixJSONClient(tmp_path/"none.sock",key,service="authority")
    with pytest.raises(ValueError, match="request too large"):
        client.call("handshake",{"x":"y"*40_000})
    authority=UnixAuthorityClient(client)
    with pytest.raises(RuntimeError, match="operation forbidden"):
        authority._call("create_license",{})
