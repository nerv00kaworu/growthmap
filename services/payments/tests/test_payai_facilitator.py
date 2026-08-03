"""PayAI public-capability and exact-origin contract tests; no payment is sent."""
import hashlib
import json

import pytest

from growthmap_payments.facilitator import (
    PAYAI_FACILITATOR_ORIGIN,
    OfficialX402Facilitator,
    inspect_payai_capabilities,
)
from growthmap_payments.service import BASE_NETWORK

SIGNER = "0xB2Bd29925CBbCEA7628279c91945Ca5B98bf371B"


def capability(**changes):
    value = {
        "kinds": [{"x402Version": 2, "scheme": "exact", "network": BASE_NETWORK}],
        "extensions": ["bazaar"],
        "signers": {"eip155:*": [SIGNER]},
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def test_payai_exact_origin_provider_seam_is_pinned_and_non_authorizing():
    class Client:
        def verify(self, *args): pass
        def settle(self, *args): pass
    class Provider:
        def __init__(self): self.calls = []
        def build_x402_client(self, **kwargs): self.calls.append(kwargs); return Client()
    provider = Provider()
    adapter = OfficialX402Facilitator.from_payai_provider(provider, timeout=7.5)
    assert adapter.endpoint == PAYAI_FACILITATOR_ORIGIN
    assert provider.calls == [{"endpoint": PAYAI_FACILITATOR_ORIGIN, "timeout": 7.5}]
    assert not hasattr(adapter, "authorized") and not hasattr(adapter, "_authorized_provider_injected")


def test_payai_capability_snapshot_accepts_base_v2_exact_and_returns_digest():
    raw = capability()
    evidence = inspect_payai_capabilities(raw)
    assert evidence.base_exact_v2 is True
    assert evidence.document_sha256 == hashlib.sha256(raw).hexdigest()
    assert evidence.evm_signers == (SIGNER.lower(),)


@pytest.mark.parametrize("raw,pattern", [
    (b"", "invalid PayAI capability document"),
    (b"not-json", "invalid PayAI capability document"),
    (b"{}", "invalid PayAI capability document"),
    (capability(kinds=[]), "Base x402 v2 exact capability unavailable"),
    (capability(kinds=[{"x402Version": 1, "scheme": "exact", "network": "base"}]), "Base x402 v2 exact capability unavailable"),
    (capability(signers={}), "Base x402 v2 exact capability unavailable"),
    (capability(signers={"eip155:*": ["not-an-address"]}), "invalid PayAI capability signer"),
    (capability(signers={"eip155:*": [SIGNER, SIGNER.lower()]}), "invalid PayAI capability signer"),
])
def test_payai_capability_snapshot_fails_closed(raw, pattern):
    with pytest.raises(ValueError, match=pattern):
        inspect_payai_capabilities(raw)


def test_payai_capability_duplicate_or_case_colliding_json_keys_rejected():
    for raw in (
        b'{"kinds":[],"kinds":[],"signers":{}}',
        b'{"kinds":[],"Kinds":[],"signers":{}}',
        b'{"kinds":[],"signers":{"eip155:*":["0xB2Bd29925CBbCEA7628279c91945Ca5B98bf371B"],"EIP155:*":[]}}',
    ):
        with pytest.raises(ValueError, match="invalid PayAI capability document"):
            inspect_payai_capabilities(raw)


def test_payai_capability_document_size_is_bounded():
    with pytest.raises(ValueError, match="invalid PayAI capability document"):
        inspect_payai_capabilities(b"x" * 65_537)
