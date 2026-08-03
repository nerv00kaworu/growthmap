"""Finality sidecar signatures keep the private signing key outside payments."""
import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from growthmap_payments.finality import SignedFinalityReconciler, canonical_payload
from growthmap_payments.service import BASE_NETWORK, BASE_USDC
from test_payments import RECIPIENT

DOMAIN = b"growthmap-signed-finality-v1\0"
KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
FIXED_NOW = datetime(2090, 8, 2, tzinfo=timezone.utc)
PAYER = "0x" + "2" * 40
TX = "0x" + "3" * 64


def intent():
    return {"intent_id":"intent-1","proof_hash":"4"*64,"nonce_hash":"5"*64,"order_id":"order-1","verified_payer":PAYER,"amount_minor":10_000_000,"created_at":"2090-08-01T00:00:00+00:00"}


def payload(value):
    return {"outcome":"paid","proof_hash":value["proof_hash"],"nonce_hash":value["nonce_hash"],"order_id":value["order_id"],"payer":PAYER,"tx_hash":TX,"evidence_hash":hashlib.sha256(b"receipt").hexdigest(),"source":"base.rpc.official","finality_at":value["created_at"],"finality_basis":"base.rpc.finalized_ancestor","network":BASE_NETWORK,"asset":BASE_USDC.lower(),"payee":RECIPIENT,"amount_minor":value["amount_minor"]}


def document(value, key=KEY):
    signature = base64.b64encode(key.sign(DOMAIN + canonical_payload(value))).decode()
    return canonical_payload({"signature": signature, "payload": value})


class Provider:
    def __init__(self, raw): self.raw = raw
    def finality_evidence(self, ignored): return self.raw


def reconciler(raw, public=PUBLIC):
    return SignedFinalityReconciler(Provider(raw), public, payee=RECIPIENT, now=lambda: FIXED_NOW)


def test_signed_finality_normalizes_exact_paid_document_without_private_key():
    value = payload(intent())
    result = reconciler(document(value)).reconcile(intent())
    assert result["outcome"] == "paid" and result["tx_hash"] == value["tx_hash"]
    assert not hasattr(reconciler(document(value)), "private_key")


def test_wrong_key_mutation_and_mac_envelope_fail_closed():
    value = payload(intent())
    other = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="verification failed"):
        reconciler(document(value, other)).reconcile(intent())
    doc = json.loads(document(value)); doc["payload"]["amount_minor"] = 1
    with pytest.raises(ValueError, match="verification failed"):
        reconciler(canonical_payload(doc)).reconcile(intent())
    with pytest.raises(ValueError, match="signed finality envelope"):
        reconciler(canonical_payload({"mac": "0" * 64, "payload": value})).reconcile(intent())


def test_signed_finality_public_key_and_document_bounds_fail_closed():
    with pytest.raises(RuntimeError, match="public key invalid"):
        SignedFinalityReconciler(Provider(b"x"), b"bad", payee=RECIPIENT)
    with pytest.raises(ValueError, match="invalid signed finality document"):
        reconciler(b"x" * 16_385).reconcile(intent())
