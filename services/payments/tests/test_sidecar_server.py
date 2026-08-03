"""Unix sidecar server/client E2E, replay, peer and operation boundaries."""
import hashlib
import hmac
import json
import os
import socket
import threading

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.skipif(os.name == "nt", reason="production sidecars use Linux AF_UNIX/SO_PEERCRED")

from growthmap_payments.sidecar_server import AuthenticatedUnixSidecarServer, AuthorityHandler, FinalityHandler, ReplayWindow
from growthmap_payments.unix_transport import AuthenticatedUnixJSONClient, UnixAuthorityClient, UnixFinalityAuthenticator
from test_signed_finality import payload, intent
from test_authority_identity_binding import signer_setup, make_authority, configured
from test_device_activation_closure import paid
from licensing.signer_ceremony import OfflineFixtureMonotonicAnchor

KEY=b"isolated-sidecar-transport-key-32bytes-minimum"


def keyfile(tmp_path):
    p=tmp_path/"key";p.write_bytes(KEY);p.chmod(0o600);return p


def run_once(server):
    thread=threading.Thread(target=server.serve_once);thread.start();return thread


class Signer:
    def __init__(self): self.key=Ed25519PrivateKey.generate();self.calls=0
    def sign(self,message):self.calls+=1;return self.key.sign(message)


class Authority:
    def __init__(self):self.calls=[]
    def handshake(self):self.calls.append(("handshake",{}));return {"authority_id":"growthmap-authority-primary","key_id":"key-1","generation":1,"public_key_sha256":"0"*64,"attestation":"test"}
    def create_external_entitlement(self,**kwargs):self.calls.append(("create",kwargs));return {"ok":"created"}
    def read_external_entitlement_acknowledgement(self,**kwargs):return {"ok":"read"}
    def revoke_external_entitlement(self,**kwargs):return {"ok":"revoked"}
    def read_external_revocation_acknowledgement(self,**kwargs):return {"ok":"revocation-read"}


def test_finality_server_client_e2e_and_socket_mode(tmp_path):
    signer=Signer();server=AuthenticatedUnixSidecarServer(tmp_path/"finality.sock",keyfile(tmp_path),service="finality",handler=FinalityHandler(signer),expected_peer_uid=os.getuid());server.bind()
    assert (os.stat(server.socket_path).st_mode&0o777)==0o600
    thread=run_once(server);client=UnixFinalityAuthenticator(AuthenticatedUnixJSONClient(server.socket_path,server.transport_key_file,service="finality"));raw=client.authenticate_finality_payload(payload(intent()))
    assert b'"signature"' in raw and signer.calls==1
    thread.join(2);server.close();assert not server.socket_path.exists()


def test_authority_server_allowlisted_e2e(tmp_path):
    authority=Authority();server=AuthenticatedUnixSidecarServer(tmp_path/"authority.sock",keyfile(tmp_path),service="authority",handler=AuthorityHandler(authority),expected_peer_uid=os.getuid());server.bind();thread=run_once(server)
    client=UnixAuthorityClient(AuthenticatedUnixJSONClient(server.socket_path,server.transport_key_file,service="authority"));assert client.handshake()["generation"]==1
    thread.join(2);server.close();assert authority.calls==[("handshake",{})]
    with pytest.raises(ValueError,match="Authority operation forbidden"):AuthorityHandler(authority).dispatch("create_license",{})


def raw_request(service,operation,nonce,args,key=KEY):
    core={"service":service,"operation":operation,"nonce":nonce,"arguments":args};return json.dumps({**core,"mac":hmac.new(key,b"growthmap-unix-request-v1\0"+json.dumps(core,sort_keys=True,separators=(",", ":")).encode(),hashlib.sha256).hexdigest()},sort_keys=True,separators=(",", ":")).encode()


def exchange(path,raw):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as c:c.connect(str(path));c.sendall(raw);c.shutdown(socket.SHUT_WR);return json.loads(c.recv(32768))


def test_replay_is_rejected_without_second_sign(tmp_path):
    signer=Signer();server=AuthenticatedUnixSidecarServer(tmp_path/"r.sock",keyfile(tmp_path),service="finality",handler=FinalityHandler(signer),expected_peer_uid=os.getuid());server.bind();nonce="a"*64;raw=raw_request("finality","sign_finality",nonce,{"payload":payload(intent())})
    first_thread=run_once(server);first=exchange(server.socket_path,raw);first_thread.join(2);assert first["ok"] is True and signer.calls==1
    second_thread=run_once(server);second=exchange(server.socket_path,raw);second_thread.join(2);server.close();assert second["ok"] is False and signer.calls==1


def test_bad_mac_wrong_service_unknown_operation_and_oversize_fail_closed(tmp_path):
    signer=Signer();server=AuthenticatedUnixSidecarServer(tmp_path/"bad.sock",keyfile(tmp_path),service="finality",handler=FinalityHandler(signer),expected_peer_uid=os.getuid());server.bind()
    cases=[raw_request("finality","sign_finality","b"*64,{"payload":payload(intent())},b"x"*40),raw_request("authority","sign_finality","c"*64,{"payload":payload(intent())}),raw_request("finality","create_license","d"*64,{})]
    for raw in cases:
        thread=run_once(server);response=exchange(server.socket_path,raw);thread.join(2);assert response["ok"] is False
    thread=run_once(server)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:client.connect(str(server.socket_path));client.sendall(b"x"*32769);client.shutdown(socket.SHUT_WR);assert client.recv(1)==b""
    thread.join(2);server.close();assert signer.calls==0


def test_payment_to_real_authority_sidecar_crossing_and_restart_readback(tmp_path):
    signing_key,public,descriptor=signer_setup();authority_db=tmp_path/"authority.sqlite";authority=make_authority(authority_db,signing_key,public,descriptor,OfflineFixtureMonotonicAnchor());payment=configured(tmp_path/"payments.sqlite",authority);order=paid(payment)
    transport=keyfile(tmp_path);socket_path=tmp_path/"authority-real.sock"
    server=AuthenticatedUnixSidecarServer(socket_path,transport,service="authority",handler=AuthorityHandler(authority),expected_peer_uid=os.getuid());server.bind()
    # deliver_entitlement performs repeated handshake + operation + readback over
    # separate one-request connections; serve the exact finite crossing sequence.
    threads=[]
    for _ in range(6):threads.append(run_once(server))
    client=UnixAuthorityClient(AuthenticatedUnixJSONClient(socket_path,transport,service="authority"));result=payment.deliver_entitlement(order["order_id"],client)
    for thread in threads:thread.join(3)
    server.close();assert result["license_id"].startswith("gm_")
    assert payment.config.db_path != authority_db
    with payment._db() as db:assert db.execute("select state from orders").fetchone()[0]=="license_issued"
    # Reopen Authority against the same isolated DB/signer ceremony; durable
    # readback remains exact and no payment DB is attached or copied.
    reopened=make_authority(authority_db,signing_key,public,descriptor,authority.anchor)
    with reopened._connect() as db:source_id=db.execute("select source_id from external_entitlements").fetchone()[0]
    assert reopened.read_external_entitlement_acknowledgement(source="x402",source_id=source_id,signer_identity=reopened.handshake())["license_id"]==result["license_id"]


def test_bind_refuses_existing_path_and_replay_window_bounds(tmp_path):
    existing=tmp_path/"existing";existing.write_text("do-not-clobber")
    server=AuthenticatedUnixSidecarServer(existing,keyfile(tmp_path),service="finality",handler=FinalityHandler(Signer()),expected_peer_uid=os.getuid())
    with pytest.raises(RuntimeError,match="already exists"):server.bind()
    window=ReplayWindow(128);window.consume("e"*64)
    with pytest.raises(ValueError,match="replayed"):window.consume("e"*64)
