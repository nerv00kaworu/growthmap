import base64, importlib, json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from desktop.entitlements import canonical_payload, verify_document

def signed_doc(private, **changes):
    doc={"edition":"pro","license_id":"TEST-ONLY-001","expires_at":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),"max_active_projects":None}
    doc.update(changes); doc["signature"]=base64.b64encode(private.sign(canonical_payload(doc))).decode(); return doc

def test_license_fail_closed_and_test_only_valid_fixture(tmp_path):
    private=Ed25519PrivateKey.generate()  # ephemeral TEST-ONLY key; never committed
    pub=tmp_path/'public.pem'; pub.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    valid=signed_doc(private); assert verify_document(valid,pub).max_active_projects is None
    tampered=dict(valid,max_active_projects=99); assert not verify_document(tampered,pub).valid
    expired=signed_doc(private,expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()); assert verify_document(expired,pub).reason=='expired'
    assert not verify_document({"signature":"bad"},pub).valid
    assert verify_document(signed_doc(private, edition="enterprise"), pub).reason == "invalid_edition"
    assert verify_document(signed_doc(private, max_active_projects=True), pub).reason == "invalid_limit"
    assert verify_document(signed_doc(private, license_id=""), pub).reason == "invalid_license_id"
    extra = signed_doc(private); extra["unexpected"] = "field"
    assert verify_document(extra, pub).reason == "invalid_document"
    naive = signed_doc(private, expires_at="2099-01-01T00:00:00")
    assert verify_document(naive, pub).reason == "invalid_expiry"
    placeholder = tmp_path / "placeholder.pem"; placeholder.write_text("-----BEGIN PUBLIC KEY-----\nREPLACE_WITH_PRODUCTION\n-----END PUBLIC KEY-----\n")
    assert verify_document(valid, placeholder).reason == "placeholder_public_key"

def test_desktop_env_write_forbidden(monkeypatch,tmp_path):
    monkeypatch.setenv('GROWTHMAP_DESKTOP_MODE','1'); monkeypatch.setenv('GROWTHMAP_ENV_FILE',str(tmp_path/'forbidden.env'))
    import desktop.secrets, api.routes
    importlib.reload(desktop.secrets); importlib.reload(api.routes)
    with pytest.raises(Exception) as error: api.routes._write_env_value('SAFE_KEY','secret')
    assert getattr(error.value,'status_code',None)==403
    assert not (tmp_path/'forbidden.env').exists()
