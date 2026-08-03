"""Offline Base finalized-receipt observer contract tests."""
import hashlib
from datetime import datetime, timezone

import pytest

from growthmap_payments.base_finality import (
    BASE_CHAIN_ID_HEX, OFFICIAL_BASE_RPC_ORIGIN, TRANSFER_TOPIC,
    BaseRPCFinalityEvidenceProvider, OfficialBaseRPCTransport,
)
from growthmap_payments.finality import sign_test_document
from growthmap_payments.service import BASE_NETWORK, BASE_USDC
from test_payments import MAC_KEY, RECIPIENT

PAYER = "0x" + "2" * 40
TX = "0x" + "3" * 64
BLOCK = "0x" + "4" * 64
FINALIZED = "0x" + "5" * 64
STAMP = int(datetime(2090, 8, 2, tzinfo=timezone.utc).timestamp())


def topic(address): return "0x" + "0" * 24 + address[2:]


def intent(**changes):
    value = {
        "intent_id": "intent-1", "proof_hash": "6" * 64, "nonce_hash": "7" * 64,
        "order_id": "order-1", "verified_payer": PAYER, "amount_minor": 10_000_000,
        "created_at": datetime.fromtimestamp(STAMP - 60, timezone.utc).isoformat(),
    }
    value.update(changes); return value


def candidate(**changes):
    value = {
        "intent_id": "intent-1", "tx_hash": TX, "payer": PAYER, "network": BASE_NETWORK,
        "amount_minor": 10_000_000, "source": "payai.facilitator.accepted", "response_hash": "8" * 64,
    }
    value.update(changes); return value


def log(**changes):
    value = {"address": BASE_USDC.lower(), "topics": [TRANSFER_TOPIC, topic(PAYER), topic(RECIPIENT)], "data": "0x" + f"{10_000_000:064x}"}
    value.update(changes); return value


class Candidates:
    def __init__(self, value=None): self.value = value or candidate()
    def candidate_for_intent(self, intent_id): return dict(self.value)


class Authenticator:
    def __init__(self): self.payloads = []
    def authenticate_finality_payload(self, payload):
        self.payloads.append(payload)
        return sign_test_document(payload, MAC_KEY)


class RPC:
    def __init__(self, **changes):
        self.values = {
            "eth_chainId": BASE_CHAIN_ID_HEX,
            "eth_getTransactionReceipt": {"transactionHash": TX, "status": "0x1", "blockNumber": "0x64", "blockHash": BLOCK, "logs": [log()]},
            "eth_getBlockByHash": {"hash": BLOCK, "number": "0x64", "timestamp": hex(STAMP)},
            "eth_getBlockByNumber": {"hash": FINALIZED, "number": "0x70", "timestamp": hex(STAMP + 24)},
        }
        self.values.update(changes); self.calls = []
    def call(self, method, params): self.calls.append((method, params)); return self.values[method]


def provider(rpc=None, candidates=None, authenticator=None):
    return BaseRPCFinalityEvidenceProvider(rpc or RPC(), candidates or Candidates(), authenticator or Authenticator(), payee=RECIPIENT, source="base.rpc.primary")


def test_exact_finalized_usdc_transfer_is_sent_to_external_authenticator():
    auth = Authenticator(); rpc = RPC(); raw = provider(rpc=rpc, authenticator=auth).finality_evidence(intent())
    assert raw and len(auth.payloads) == 1
    payload = auth.payloads[0]
    assert payload["outcome"] == "paid" and payload["tx_hash"] == TX
    assert payload["payer"] == PAYER and payload["payee"] == RECIPIENT
    assert payload["amount_minor"] == 10_000_000 and payload["network"] == BASE_NETWORK
    assert payload["asset"] == BASE_USDC.lower() and payload["finality_basis"] == "base.rpc.finalized_ancestor"
    assert rpc.calls == [("eth_chainId", []), ("eth_getTransactionReceipt", [TX]), ("eth_getBlockByHash", [BLOCK, False]), ("eth_getBlockByNumber", ["finalized", False])]


@pytest.mark.parametrize("rpc,pattern", [
    (RPC(eth_chainId="0x1"), "chain mismatch"),
    (RPC(eth_getTransactionReceipt=None), "invalid Base RPC receipt"),
    (RPC(eth_getTransactionReceipt={"transactionHash": TX, "status": "0x0", "blockNumber": "0x64", "blockHash": BLOCK, "logs": [log()]}), "receipt mismatch"),
    (RPC(eth_getTransactionReceipt={"transactionHash": "0x" + "9" * 64, "status": "0x1", "blockNumber": "0x64", "blockHash": BLOCK, "logs": [log()]}), "receipt mismatch"),
    (RPC(eth_getBlockByHash={"hash": "0x" + "9" * 64, "number": "0x64", "timestamp": hex(STAMP)}), "block not finalized"),
    (RPC(eth_getBlockByNumber={"hash": FINALIZED, "number": "0x63", "timestamp": hex(STAMP)}), "block not finalized"),
    (RPC(eth_getTransactionReceipt={"transactionHash": TX, "status": "0x1", "blockNumber": "0x064", "blockHash": BLOCK, "logs": [log()]}), "quantity"),
])
def test_chain_receipt_canonicality_and_finalized_ancestry_fail_closed(rpc, pattern):
    with pytest.raises(ValueError, match=pattern): provider(rpc=rpc).finality_evidence(intent())


@pytest.mark.parametrize("logs", [
    [],
    [log(address="0x" + "9" * 40)],
    [log(topics=[TRANSFER_TOPIC, topic("0x" + "9" * 40), topic(RECIPIENT)])],
    [log(topics=[TRANSFER_TOPIC, topic(PAYER), topic("0x" + "9" * 40)])],
    [log(data="0x" + f"{1:064x}")],
    [log(), log()],
])
def test_exact_one_usdc_transfer_binding_required(logs):
    receipt = {"transactionHash": TX, "status": "0x1", "blockNumber": "0x64", "blockHash": BLOCK, "logs": logs}
    with pytest.raises(ValueError, match="USDC transfer mismatch"):
        provider(rpc=RPC(eth_getTransactionReceipt=receipt)).finality_evidence(intent())


@pytest.mark.parametrize("changes", [
    {"intent_id": "other"}, {"tx_hash": "not-a-tx"}, {"payer": "0x" + "9" * 40},
    {"network": "eip155:1"}, {"amount_minor": 1}, {"response_hash": "bad"},
])
def test_candidate_must_bind_exact_intent(changes):
    with pytest.raises(ValueError, match="candidate binding mismatch"):
        provider(candidates=Candidates(candidate(**changes))).finality_evidence(intent())


def test_timestamp_before_intent_and_dependency_failures_are_rejected():
    late = intent(created_at=datetime.fromtimestamp(STAMP + 1, timezone.utc).isoformat())
    with pytest.raises(ValueError, match="timestamp invalid"):
        provider().finality_evidence(late)
    class Broken:
        def call(self, method, params): raise RuntimeError("provider-secret")
    with pytest.raises(ValueError, match="dependency unavailable") as caught:
        provider(rpc=Broken()).finality_evidence(intent())
    assert "provider-secret" not in str(caught.value)


def test_official_rpc_transport_is_exact_read_only_and_bounded(monkeypatch):
    transport = OfficialBaseRPCTransport(timeout=5)
    assert OFFICIAL_BASE_RPC_ORIGIN == "https://mainnet.base.org" and transport.timeout == 5.0
    for method in ("eth_sendRawTransaction", "eth_sendTransaction", "personal_sign", "eth_sign", "debug_traceTransaction", "eth_getLogs"):
        with pytest.raises(ValueError, match="method forbidden"):
            transport.call(method, [])
    with pytest.raises(ValueError, match="method forbidden"):
        transport.call("eth_chainId", {})
    with pytest.raises(RuntimeError, match="timeout invalid"):
        OfficialBaseRPCTransport(timeout=0)
    with pytest.raises(RuntimeError, match="timeout invalid"):
        OfficialBaseRPCTransport(timeout=True)


def test_official_rpc_dns_rejects_private_and_empty_answers(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="DNS rejected"):
        OfficialBaseRPCTransport._public_addresses()
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [])
    with pytest.raises(ValueError, match="DNS unavailable"):
        OfficialBaseRPCTransport._public_addresses()


def test_invalid_payee_source_and_empty_authenticator_fail_closed():
    with pytest.raises(RuntimeError, match="payee invalid"):
        BaseRPCFinalityEvidenceProvider(RPC(), Candidates(), Authenticator(), payee="bad", source="base.rpc")
    with pytest.raises(RuntimeError, match="source invalid"):
        BaseRPCFinalityEvidenceProvider(RPC(), Candidates(), Authenticator(), payee=RECIPIENT, source="Bad Source")
    class Empty:
        def authenticate_finality_payload(self, payload): return b""
    with pytest.raises(ValueError, match="authenticator unavailable"):
        provider(authenticator=Empty()).finality_evidence(intent())
