"""Local-only GMG1 desktop-to-HTTP contract: no deployment composition or real signer."""
import base64
import json
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.entitlements import verify_document
from licensing.authority import LicenseAuthority
from licensing.authority_api import create_authority_app
from licensing.signer_ceremony import DOMAIN, PURPOSE, OfflineFixtureMonotonicAnchor

ROOT = Path(__file__).resolve().parents[3]


class ExternalTestSigner:
    """Test-only injected signer; private material stays in pytest's temp directory."""
    def __init__(self, key): self.key = key
    def sign(self, message): return self.key.sign(message)


class FixtureDescriptor:
    def __init__(self, authority): self.authority = authority
    def descriptor(self): return self.authority.handshake() | {"status": "active"}


class FixtureAnchorVerifier:
    def verify(self, _descriptor): return True


def external_authority(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    descriptor = {
        "schema_version": 1, "purpose": PURPOSE, "domain": DOMAIN, "algorithm": "Ed25519",
        "authority_id": "gift-http-contract-test", "key_id": "test-only-external-signer",
        "generation": 1, "activated_at": "2026-08-02T00:00:00Z", "predecessor_generation": None,
        "public_key_sha256": __import__("hashlib").sha256(public).hexdigest(),
        "provider_attestation_id": "test-only-anchor",
    }
    return LicenseAuthority.from_external_signer(
        tmp_path / "authority.sqlite", signer=ExternalTestSigner(key), ceremony_descriptor=descriptor,
        reviewed_public_key=public, generation_anchor=OfflineFixtureMonotonicAnchor(),
        now=lambda: datetime(2026, 8, 8, tzinfo=timezone.utc),
    )


class GiftHttpFixture:
    def __init__(self, authority, base, server, thread, listener):
        self.authority = authority
        self.base = base
        self.server = server
        self.thread = thread
        self.listener = listener

    def shutdown(self):
        """Stop the loopback fixture; safe to call again from fixture cleanup."""
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=3)
        try:
            self.listener.close()
        except OSError:
            pass
        if self.thread.is_alive():
            self.thread.join(timeout=3)
        assert not self.thread.is_alive()


@pytest.fixture
def gift_http(tmp_path):
    authority = external_authority(tmp_path)
    app = create_authority_app(
        authority=authority, signer_descriptor_provider=FixtureDescriptor(authority),
        anchor_verifier=FixtureAnchorVerifier(),
    )
    # Keep the listening socket open until Uvicorn owns it so no other local process
    # can claim the ephemeral port between allocation and server startup.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    base = f"http://127.0.0.1:{port}"
    fixture = GiftHttpFixture(authority, base, server, thread, listener)
    try:
        thread.start()
        for _ in range(100):
            try:
                urlopen(base + "/v1/authority/identity", timeout=.1).read()
                break
            except OSError:
                time.sleep(.02)
        else:
            pytest.fail("gift loopback server did not start")
        yield fixture
    finally:
        fixture.shutdown()


def desktop_activate(claim_key, loopback_base):
    # The production client rightfully requires a canonical HTTPS origin. This test-only
    # fetch seam maps that logical origin to the local cleartext loopback ASGI fixture;
    # activateLicenseKey itself still owns parsing, challenge signing, and both requests.
    script = r'''
const crypto=require('node:crypto');
const {activateLicenseKey}=require('./desktop/activation-client');
const [key,base]=process.argv.slice(1);
const {privateKey,publicKey}=crypto.generateKeyPairSync('ed25519');
const identity={privateKeyPem:privateKey.export({format:'pem',type:'pkcs8'}).toString(),publicKey:publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64')};
const fetchImpl=(url,options)=>{const target=new URL(url);target.protocol='http:';target.host=new URL(base).host;return fetch(target,options);};
activateLicenseKey({activationKey:key,activationApiOrigin:'https://gift-contract.test',deviceIdentity:identity,fetchImpl})
 .then(certificate=>process.stdout.write(JSON.stringify({certificate,devicePublicKey:identity.publicKey})))
 .catch(error=>{process.stderr.write(error.message);process.exit(23);});
'''
    return subprocess.run(["node", "-e", script, claim_key, loopback_base], cwd=ROOT, text=True, capture_output=True, check=False)


def response_json(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_gmg1_desktop_http_challenge_persisted_certificate_offline_reread_rotation_revoke_and_seat_replacement(gift_http, tmp_path):
    authority, base = gift_http.authority, gift_http.base
    created = authority.create_gift()
    old_key, gift_id = created["claim_key"], created["gift_id"]

    first = response_json(desktop_activate(old_key, base))
    public_key = tmp_path / "reviewed-authority-public.pem"
    public_key.write_bytes(authority.public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    now = datetime.fromisoformat(first["certificate"]["issued_at"].replace("Z", "+00:00"))
    imported = tmp_path / "desktop-license.json"
    imported.write_text(json.dumps(first["certificate"], separators=(",", ":")))

    rotated = authority.recover_gift(gift_id)
    with pytest.raises(HTTPError) as stale:
        urlopen(Request(base + "/v1/gifts/claim/challenge", data=json.dumps({"claim_key": old_key, "device_public_key": first["devicePublicKey"]}).encode(), headers={"Content-Type": "application/json"}), timeout=5)
    assert stale.value.code == 404

    second = response_json(desktop_activate(rotated["claim_key"], base))
    seat_full = desktop_activate(rotated["claim_key"], base)
    assert seat_full.returncode == 23 and "授權碼無效或尚未付款" in seat_full.stderr
    devices = authority.list_gift_devices(gift_id)
    assert {row["device_id"] for row in devices} == {first["certificate"]["device_id"], second["certificate"]["device_id"]}
    released = {"deactivated": authority.deactivate_gift_device(gift_id, first["certificate"]["device_id"])}
    assert released == {"deactivated": True}
    replacement = response_json(desktop_activate(rotated["claim_key"], base))
    assert replacement["certificate"]["device_id"] not in {first["certificate"]["device_id"], second["certificate"]["device_id"]}
    devices = authority.list_gift_devices(gift_id)
    assert next(row for row in devices if row["device_id"] == first["certificate"]["device_id"])["deactivated_at"] is not None
    assert len([row for row in devices if row["deactivated_at"] is None]) == 2

    assert authority.revoke_gift(gift_id)["status"] == "revoked"
    revoked = desktop_activate(rotated["claim_key"], base)
    assert revoked.returncode == 23 and "授權碼無效或尚未付款" in revoked.stderr

    # Mechanically prove persisted-certificate verification is offline: stop the
    # only HTTP fixture and confirm its thread is gone before reading the file.
    gift_http.shutdown()
    assert not gift_http.thread.is_alive()
    persisted = json.loads(imported.read_text())
    verified = verify_document(persisted, public_key, now=now, device_public_key=first["devicePublicKey"])
    assert verified.valid and verified.state == "paid" and verified.mutations_allowed
    assert old_key not in imported.read_text()
