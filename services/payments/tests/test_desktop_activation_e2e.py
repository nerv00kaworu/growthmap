"""Website-issued key to desktop certificate and offline restart contract."""
import base64
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from desktop.entitlements import verify_document
from growthmap_payments.api import MockFacilitator, create_app
from licensing.authority import activation_challenge
from test_device_activation_closure import setup, paid

ROOT = Path(__file__).resolve().parents[3]


def node_device_and_proof(license_id: str, nonce: str) -> dict:
    script = r"""
const crypto=require('node:crypto');
const [licenseId,nonce]=process.argv.slice(1);
const {privateKey,publicKey}=crypto.generateKeyPairSync('ed25519');
const publicRaw=publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64');
const canonical=JSON.stringify({device_public_key:publicRaw,license_id:licenseId,nonce});
const proof=crypto.sign(null,Buffer.concat([Buffer.from('growthmap-activation-request-v1\0'),Buffer.from(canonical)]),privateKey).toString('base64');
process.stdout.write(JSON.stringify({publicRaw,proof}));
"""
    completed = subprocess.run(["node", "-e", script, license_id, nonce], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


def test_formatted_key_node_proof_real_authority_offline_restart(tmp_path):
    service, authority, cfg = setup(tmp_path)
    order = paid(service)
    entitlement = service.deliver_entitlement(order["order_id"], authority)
    activation_key = f'GM1.{order["order_id"]}.{order["recovery_code"]}'
    # The exact desktop parser accepts the server-derived formatted capability.
    parser = "const {parseActivationKey}=require('./desktop/activation-client');process.stdout.write(JSON.stringify(parseActivationKey(process.argv[1])));"
    parsed = json.loads(subprocess.run(["node", "-e", parser, activation_key], cwd=ROOT, text=True, capture_output=True, check=True).stdout)
    assert parsed == {"orderId": order["order_id"], "recoveryCode": order["recovery_code"]}

    client = TestClient(create_app(cfg, MockFacilitator(), authority=authority))
    # First obtain a challenge using a temporary Node identity public key, then
    # sign the server nonce in Node with exactly the desktop domain/canonical form.
    # We generate the durable identity first so the public key used in the
    # challenge is the same key that signs the proof.
    node_script = r"""
const crypto=require('node:crypto');
const {privateKey,publicKey}=crypto.generateKeyPairSync('ed25519');
process.stdout.write(JSON.stringify({privateKeyPem:privateKey.export({format:'pem',type:'pkcs8'}).toString(),publicRaw:publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64')}));
"""
    device = json.loads(subprocess.run(["node", "-e", node_script], cwd=ROOT, text=True, capture_output=True, check=True).stdout)
    issued = client.post("/v1/activation/challenge", json={"order_id": parsed["orderId"], "recovery_code": parsed["recoveryCode"], "device_public_key": device["publicRaw"]})
    assert issued.status_code == 200
    challenge = issued.json()["challenge"]
    sign_script = r"""
const crypto=require('node:crypto');
const [pem64,licenseId,publicRaw,nonce]=process.argv.slice(1);
const canonical=JSON.stringify({device_public_key:publicRaw,license_id:licenseId,nonce});
const proof=crypto.sign(null,Buffer.concat([Buffer.from('growthmap-activation-request-v1\0'),Buffer.from(canonical)]),crypto.createPrivateKey(Buffer.from(pem64,'base64').toString())).toString('base64');
process.stdout.write(proof);
"""
    proof = subprocess.run(["node", "-e", sign_script, base64.b64encode(device["privateKeyPem"].encode()).decode(), entitlement["license_id"], device["publicRaw"], challenge["nonce"]], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    completed = client.post("/v1/activation/complete", json={"challenge_id": challenge["challenge_id"], "proof": proof})
    assert completed.status_code == 200
    certificate = completed.json()["certificate"]

    public_key = tmp_path / "license-public.pem"
    public_key.write_bytes(authority.public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    now = datetime.fromisoformat(certificate["issued_at"].replace("Z", "+00:00"))
    first = verify_document(certificate, public_key, now=now, device_public_key=device["publicRaw"])
    assert first.state == "paid" and first.valid and first.mutations_allowed
    # Simulate durable local import and an offline process restart. No API,
    # facilitator, RPC, order, recovery code, or payment DB is needed to verify.
    local_license = tmp_path / "desktop-license.json"
    local_license.write_text(json.dumps(certificate, separators=(",", ":")))
    restarted = verify_document(json.loads(local_license.read_text()), public_key, now=now, device_public_key=device["publicRaw"])
    assert restarted == first
    assert activation_key not in local_license.read_text() and order["recovery_code"] not in local_license.read_text()


def test_wrong_key_wrong_device_and_replayed_challenge_fail_closed(tmp_path):
    service, authority, cfg = setup(tmp_path)
    order = paid(service); entitlement = service.deliver_entitlement(order["order_id"], authority)
    client = TestClient(create_app(cfg, MockFacilitator(), authority=authority))
    wrong = client.post("/v1/activation/challenge", json={"order_id": order["order_id"], "recovery_code": "A" * 32, "device_public_key": base64.b64encode(b"x" * 32).decode()})
    assert wrong.status_code == 404 and wrong.json() == {"state": "not_found_or_unavailable"}
    key = Ed25519PrivateKey.generate(); public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    issued = client.post("/v1/activation/challenge", json={"order_id": order["order_id"], "recovery_code": order["recovery_code"], "device_public_key": public}).json()["challenge"]
    bad = base64.b64encode(b"x" * 64).decode()
    assert client.post("/v1/activation/complete", json={"challenge_id": issued["challenge_id"], "proof": bad}).status_code == 404
    proof = base64.b64encode(key.sign(activation_challenge(entitlement["license_id"], public, issued["nonce"]))).decode()
    first = client.post("/v1/activation/complete", json={"challenge_id": issued["challenge_id"], "proof": proof})
    replay = client.post("/v1/activation/complete", json={"challenge_id": issued["challenge_id"], "proof": proof})
    assert first.status_code == 200 and replay.content == first.content
    certificate = first.json()["certificate"]
    public_key = tmp_path / "authority-public.pem"; public_key.write_bytes(authority.public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    now = datetime.fromisoformat(certificate["issued_at"].replace("Z", "+00:00"))
    other = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    assert verify_document(certificate, public_key, now=now, device_public_key=other).reason == "wrong_device"
