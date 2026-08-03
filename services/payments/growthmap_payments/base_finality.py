"""Strict Base receipt observer; transport/authenticator construction is not authorization."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import ssl
from datetime import datetime, timezone
from http.client import HTTPSConnection
from typing import Any, Protocol

from .finality import canonical_payload
from .service import BASE_NETWORK, BASE_USDC

BASE_CHAIN_ID_HEX = "0x2105"
OFFICIAL_BASE_RPC_ORIGIN = "https://mainnet.base.org"
_RPC_HOST = "mainnet.base.org"
_RPC_METHODS = frozenset({"eth_chainId", "eth_getTransactionReceipt", "eth_getBlockByHash", "eth_getBlockByNumber"})
_RPC_MAX_REQUEST = 2_048
_RPC_MAX_RESPONSE = 1_048_576
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_TX = re.compile(r"0x[0-9a-f]{64}")
_ADDRESS = re.compile(r"0x[0-9a-f]{40}")
_HASH = re.compile(r"[0-9a-f]{64}")
_QUANTITY = re.compile(r"0x(?:0|[1-9a-f][0-9a-f]*)")
_LABEL = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,127}")


class BaseRPCTransport(Protocol):
    def call(self, method: str, params: list[Any]) -> Any: ...


class OfficialBaseRPCTransport:
    """Low-volume beta, read-only transport pinned to Base's official origin.

    The allowlist intentionally excludes every write/sign/send method. DNS answers
    must be globally routable and are re-resolved for each fresh HTTPS connection;
    the HTTP Host/TLS SNI remains the pinned official hostname. Availability or a
    successful handshake is not production authorization.
    """

    def __init__(self, *, timeout: float = 10.0):
        if type(timeout) not in (int, float) or isinstance(timeout, bool) or not 1.0 <= float(timeout) <= 20.0:
            raise RuntimeError("official Base RPC timeout invalid")
        self.timeout = float(timeout)

    @staticmethod
    def _public_addresses() -> tuple[str, ...]:
        try:
            values = socket.getaddrinfo(_RPC_HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ValueError("official Base RPC DNS unavailable") from exc
        addresses: list[str] = []
        for value in values:
            try:
                address = str(ipaddress.ip_address(value[4][0]))
                parsed = ipaddress.ip_address(address)
            except (ValueError, IndexError) as exc:
                raise ValueError("official Base RPC DNS invalid") from exc
            if not parsed.is_global:
                raise ValueError("official Base RPC DNS rejected")
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise ValueError("official Base RPC DNS unavailable")
        return tuple(addresses)

    def call(self, method: str, params: list[Any]) -> Any:
        if type(method) is not str or method not in _RPC_METHODS or type(params) is not list:
            raise ValueError("official Base RPC method forbidden")
        request = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}, separators=(",", ":")).encode()
        if len(request) > _RPC_MAX_REQUEST:
            raise ValueError("official Base RPC request too large")
        last_error: Exception | None = None
        for address in self._public_addresses():
            connection = None
            try:
                connection = HTTPSConnection(_RPC_HOST, 443, timeout=self.timeout, context=ssl.create_default_context())
                connection._create_connection = lambda _address, timeout=None, source_address=None, _resolved=address: socket.create_connection((_resolved, 443), timeout, source_address)
                connection.request("POST", "/", body=request, headers={"Content-Type": "application/json", "Accept": "application/json", "Host": _RPC_HOST})
                response = connection.getresponse()
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > _RPC_MAX_RESPONSE):
                    raise ValueError("official Base RPC response too large")
                raw = response.read(_RPC_MAX_RESPONSE + 1)
                if response.status != 200:
                    raise ValueError("official Base RPC unavailable")
                if len(raw) > _RPC_MAX_RESPONSE:
                    raise ValueError("official Base RPC response too large")
                document = json.loads(raw.decode("utf-8", "strict"))
                if type(document) is not dict or set(document) != {"jsonrpc", "id", "result"} or document["jsonrpc"] != "2.0" or document["id"] != 1:
                    raise ValueError("official Base RPC response invalid")
                return document["result"]
            except (OSError, ssl.SSLError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
            finally:
                if connection is not None:
                    connection.close()
        raise ValueError("official Base RPC unavailable") from last_error


class FinalityEnvelopeAuthenticator(Protocol):
    def authenticate_finality_payload(self, payload: dict[str, Any]) -> bytes: ...


class SettlementCandidateLookup(Protocol):
    def candidate_for_intent(self, intent_id: str) -> dict[str, Any]: ...


def _quantity(value: Any) -> int:
    if type(value) is not str or not _QUANTITY.fullmatch(value):
        raise ValueError("invalid Base RPC quantity")
    return int(value, 16)


def _address_topic(address: str) -> str:
    return "0x" + "0" * 24 + address[2:]


def _strict_dict(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or not required.issubset(value) or any(type(key) is not str for key in value):
        raise ValueError(f"invalid Base RPC {label}")
    return value


class BaseRPCFinalityEvidenceProvider:
    """Observe one candidate on finalized Base and request an external envelope.

    RPC, candidate lookup, and envelope authentication are explicit dependencies.
    None is trusted merely because it implements this shape; the production
    composition remains independently pinned and hard-blocked elsewhere.
    """

    def __init__(self, rpc: BaseRPCTransport, candidates: SettlementCandidateLookup,
                 authenticator: FinalityEnvelopeAuthenticator, *, payee: str, source: str):
        if not _ADDRESS.fullmatch(payee or "") or payee != payee.lower():
            raise RuntimeError("Base finality payee invalid")
        if not _LABEL.fullmatch(source or ""):
            raise RuntimeError("Base finality source invalid")
        self.rpc = rpc
        self.candidates = candidates
        self.authenticator = authenticator
        self.payee = payee
        self.source = source

    def finality_evidence(self, intent: dict[str, Any]) -> bytes:
        try:
            candidate = self.candidates.candidate_for_intent(intent["intent_id"])
            payload = self._observe(intent, candidate)
            envelope = self.authenticator.authenticate_finality_payload(dict(payload))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Base finality dependency unavailable") from exc
        if not isinstance(envelope, bytes) or not envelope or len(envelope) > 16_384:
            raise ValueError("Base finality authenticator unavailable")
        return envelope

    def _observe(self, intent: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        required_intent = {"intent_id", "proof_hash", "nonce_hash", "order_id", "verified_payer", "amount_minor", "created_at"}
        required_candidate = {"intent_id", "tx_hash", "payer", "network", "amount_minor", "source", "response_hash"}
        _strict_dict(intent, required_intent, "intent")
        _strict_dict(candidate, required_candidate, "candidate")
        payer, tx_hash = intent["verified_payer"], candidate["tx_hash"]
        if (candidate["intent_id"] != intent["intent_id"] or candidate["payer"] != payer or
                candidate["network"] != BASE_NETWORK or candidate["amount_minor"] != intent["amount_minor"] or
                not _TX.fullmatch(tx_hash or "") or not _ADDRESS.fullmatch(payer or "") or
                not _HASH.fullmatch(candidate["response_hash"] or "")):
            raise ValueError("Base finality candidate binding mismatch")
        if self.rpc.call("eth_chainId", []) != BASE_CHAIN_ID_HEX:
            raise ValueError("Base finality chain mismatch")
        receipt = _strict_dict(self.rpc.call("eth_getTransactionReceipt", [tx_hash]), {
            "transactionHash", "status", "blockNumber", "blockHash", "logs"
        }, "receipt")
        if receipt["transactionHash"] != tx_hash or receipt["status"] != "0x1" or not _TX.fullmatch(receipt["blockHash"] or ""):
            raise ValueError("Base finality receipt mismatch")
        receipt_number = _quantity(receipt["blockNumber"])
        if type(receipt["logs"]) is not list:
            raise ValueError("invalid Base RPC receipt")
        canonical = _strict_dict(self.rpc.call("eth_getBlockByHash", [receipt["blockHash"], False]), {
            "hash", "number", "timestamp"
        }, "receipt block")
        finalized = _strict_dict(self.rpc.call("eth_getBlockByNumber", ["finalized", False]), {
            "hash", "number", "timestamp"
        }, "finalized block")
        if (canonical["hash"] != receipt["blockHash"] or _quantity(canonical["number"]) != receipt_number or
                _quantity(finalized["number"]) < receipt_number or not _TX.fullmatch(finalized["hash"] or "")):
            raise ValueError("Base finality block not finalized")
        timestamp = _quantity(canonical["timestamp"])
        try:
            finality_time = datetime.fromtimestamp(timestamp, timezone.utc)
            finality_at = finality_time.isoformat()
            created = datetime.fromisoformat(intent["created_at"])
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            raise ValueError("Base finality timestamp invalid") from exc
        if created.tzinfo is None or finality_time < created.astimezone(timezone.utc):
            raise ValueError("Base finality timestamp invalid")
        matches = 0
        for raw_log in receipt["logs"]:
            if type(raw_log) is not dict:
                raise ValueError("invalid Base RPC log")
            if raw_log.get("address") != BASE_USDC.lower():
                continue
            topics, data = raw_log.get("topics"), raw_log.get("data")
            if (type(topics) is list and len(topics) == 3 and topics[0] == TRANSFER_TOPIC and
                    topics[1] == _address_topic(payer) and topics[2] == _address_topic(self.payee) and
                    type(data) is str and re.fullmatch(r"0x[0-9a-f]{64}", data) and
                    int(data, 16) == intent["amount_minor"]):
                matches += 1
        if matches != 1:
            raise ValueError("Base finality USDC transfer mismatch")
        observation = {
            "candidate_response_hash": candidate["response_hash"],
            "canonical_block_hash": canonical["hash"],
            "finalized_block_hash": finalized["hash"],
            "finalized_block_number": finalized["number"],
            "receipt": receipt,
        }
        return {
            "outcome": "paid", "proof_hash": intent["proof_hash"], "nonce_hash": intent["nonce_hash"],
            "order_id": intent["order_id"], "payer": payer, "tx_hash": tx_hash,
            "evidence_hash": hashlib.sha256(canonical_payload(observation)).hexdigest(),
            "source": self.source, "finality_at": finality_at,
            "finality_basis": "base.rpc.finalized_ancestor", "network": BASE_NETWORK,
            "asset": BASE_USDC.lower(), "payee": self.payee, "amount_minor": intent["amount_minor"],
        }
