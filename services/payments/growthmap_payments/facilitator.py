"""Fail-closed adapter around the official x402 Python SDK 2.17.0."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import re
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlsplit
from .service import BASE_NETWORK, BASE_USDC

_TX = re.compile(r"0x[0-9a-fA-F]{64}")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_ORIGIN_ERROR = "facilitator endpoint must be a canonical public-DNS HTTPS origin"
# Fail closed on syntactically recognizable IANA/IETF special-use namespaces.
# ``arpa`` intentionally covers the entire infrastructure namespace, including
# reverse DNS and AS112/resolver names. ``test`` is handled separately because
# it has one explicit offline-only opt-in. Raw IDNA A-labels are not accepted.
_SPECIAL_USE_ROOTS = (
    "localhost", "local", "internal", "invalid", "example", "alt", "arpa", "onion",
    "example.com", "example.net", "example.org",
)


def _is_legacy_numeric_ipv4(host: str) -> bool:
    """Recognize 1–4 component decimal/octal/hex IPv4-like hosts offline."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return False
    numeric_component = re.compile(r"(?:[0-9]+|0[xX][0-9a-fA-F]+)")
    return all(numeric_component.fullmatch(part) for part in parts)


class FacilitatorClientProvider(Protocol):
    """Dependency-construction seam; it is not an authorization boundary."""
    def build_x402_client(self, *, endpoint: str, timeout: float) -> Any: ...

class OfficialX402Facilitator:
    """Synchronous boundary used by the durable ledger.

    ``client`` is injectable only to permit offline contract tests. Construction
    APIs do not prove authorization; the real production composition root is not
    integrated. Neither this adapter nor the ledger reads raw credential env vars.
    """
    @staticmethod
    def _validated_origin(endpoint: str, allowed_origin: str | None, *, allow_test_origin: bool = False) -> str:
        def canonical(value: str) -> str:
            if not isinstance(value, str):
                raise RuntimeError(_ORIGIN_ERROR)
            # urlsplit strips or normalizes some ASCII controls. Reject them before
            # parsing so no parser/resolver differential can change the byte string.
            if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
                raise RuntimeError(_ORIGIN_ERROR)
            try:
                parsed = urlsplit(value)
                host = parsed.hostname
                port = parsed.port
            except (TypeError, ValueError):
                raise RuntimeError(_ORIGIN_ERROR) from None
            if (parsed.scheme != "https" or not host or parsed.netloc != host or port is not None
                    or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                    or host != host.lower() or host.endswith(".") or "_" in host):
                raise RuntimeError(_ORIGIN_ERROR)
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise RuntimeError(_ORIGIN_ERROR)
            if _is_legacy_numeric_ipv4(host):
                raise RuntimeError(_ORIGIN_ERROR)
            labels = host.split(".")
            special_use = any(host == root or host.endswith("." + root) for root in _SPECIAL_USE_ROOTS)
            raw_a_label = any(label.startswith("xn--") for label in labels)
            test_only = host == "test" or host.endswith(".test")
            if (len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                    or special_use or raw_a_label or (test_only and not allow_test_origin)):
                raise RuntimeError(_ORIGIN_ERROR)
            origin = "https://" + host
            if value != origin:
                raise RuntimeError(_ORIGIN_ERROR)
            return origin

        origin = canonical(endpoint)
        if allowed_origin is not None and canonical(allowed_origin) != origin:
            raise RuntimeError(_ORIGIN_ERROR)
        return origin

    def __init__(self, endpoint: str, *, timeout: float = 20.0, client: Any = None, allowed_origin: str | None = None,
                 context_ttl=120, max_contexts=1024, _allow_test_origin: bool = False):
        self.endpoint = self._validated_origin(endpoint, allowed_origin, allow_test_origin=_allow_test_origin)
        if client is None:
            from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync
            client = HTTPFacilitatorClientSync(FacilitatorConfig(url=self.endpoint, timeout=timeout))
        self.client = client
        self._contexts: dict[str, tuple[Any, Any, str, float]] = {}
        self._lock = threading.Lock()
        self.context_ttl = context_ttl
        self.max_contexts = max_contexts

    @classmethod
    def from_client_provider(cls, endpoint: str, provider: FacilitatorClientProvider, *, timeout: float = 20.0,
                             allowed_origin: str | None = None, _allow_test_origin: bool = False):
        """Construct dependencies only; this does not prove production authorization."""
        if provider is None or not callable(getattr(provider, "build_x402_client", None)):
            raise RuntimeError("facilitator client provider required")
        origin = cls._validated_origin(endpoint, allowed_origin, allow_test_origin=_allow_test_origin)
        client = provider.build_x402_client(endpoint=origin, timeout=timeout)
        if client is None or not callable(getattr(client, "verify", None)) or not callable(getattr(client, "settle", None)):
            raise RuntimeError("facilitator provider returned invalid client")
        return cls(origin, timeout=timeout, client=client, allowed_origin=allowed_origin, _allow_test_origin=_allow_test_origin)

    @staticmethod
    def _models(signature: str, challenge: dict[str, Any]):
        from x402.http import decode_payment_signature_header
        from x402.schemas import PaymentRequirements
        if challenge.get("x402Version") != 2 or len(challenge.get("accepts", [])) != 1:
            raise ValueError("unsupported payment challenge")
        payload = decode_payment_signature_header(signature)
        requirement = PaymentRequirements.model_validate(challenge["accepts"][0])
        accepted = payload.accepted
        expected_extra = {"name":"USD Coin","version":"2","orderId":challenge["accepts"][0]["extra"]["orderId"],"product":"growthmap","majorVersion":1}
        if (payload.x402_version != 2 or accepted.scheme != "exact" or
            str(accepted.network) != BASE_NETWORK or accepted.asset.lower() != BASE_USDC.lower() or
            accepted.amount != requirement.amount or accepted.pay_to.lower() != requirement.pay_to.lower() or
            accepted.max_timeout_seconds != requirement.max_timeout_seconds or accepted.extra != expected_extra or
            requirement.scheme != "exact" or str(requirement.network) != BASE_NETWORK or
            requirement.asset.lower() != BASE_USDC.lower() or requirement.extra != expected_extra):
            raise ValueError("payment payload binding mismatch")
        authorization = payload.payload.get("authorization")
        if not isinstance(authorization, dict):
            raise ValueError("missing EVM exact authorization")
        nonce = authorization.get("nonce")
        if (not isinstance(nonce, str) or not nonce or len(nonce) > 256 or
            str(authorization.get("to","")).lower()!=requirement.pay_to.lower() or
            str(authorization.get("asset","")).lower()!=requirement.asset.lower() or
            str(authorization.get("value",""))!=str(requirement.amount) or
            authorization.get("orderId")!=expected_extra["orderId"] or
            not _ADDRESS.fullmatch(str(authorization.get("from",""))) or not isinstance(authorization.get("validBefore"),int) or authorization["validBefore"]<=int(time.time())):
            raise ValueError("invalid authorization binding")
        return payload, requirement, nonce

    def verify(self, signature: str, challenge: dict[str, Any]) -> dict[str, Any]:
        try:
            payload, requirement, nonce = self._models(signature, challenge)
            result = self.client.verify(payload, requirement)
        except Exception as exc:
            raise ValueError("facilitator verification failed") from exc
        if result.is_valid is not True or not _ADDRESS.fullmatch(result.payer or ""):
            raise ValueError("facilitator rejected payment")
        proof_id = hashlib.sha256(signature.encode("ascii")).hexdigest()
        with self._lock:
            now=time.monotonic();self._contexts={k:v for k,v in self._contexts.items() if v[3]>now}
            if proof_id in self._contexts:raise ValueError("payment proof already verified")
            if len(self._contexts)>=self.max_contexts:raise ValueError("verification context capacity reached")
            self._contexts[proof_id] = (payload, requirement, result.payer.lower(),now+self.context_ttl)
        return {"amount": requirement.amount, "nonce": nonce, "proof_id": proof_id, "payer":result.payer}

    def settle(self, signature: str, challenge: dict[str, Any]) -> dict[str, Any]:
        proof_id = hashlib.sha256(signature.encode("ascii")).hexdigest()
        payload, requirement, _ = self._models(signature, challenge)
        with self._lock:cached = self._contexts.pop(proof_id, None)
        if cached is None:
            raise RuntimeError("settle attempted without verified context")
        _,_,verified_payer,expires=cached
        if expires<=time.monotonic():raise RuntimeError("verified context expired")
        try:
            result = self.client.settle(payload, requirement)
        except Exception as exc:
            raise RuntimeError("facilitator settlement status unknown") from exc
        raw = result.model_dump(by_alias=True, exclude_none=True)
        if (result.success is not True or str(result.network) != BASE_NETWORK or
            result.amount != requirement.amount or not _TX.fullmatch(result.transaction or "") or
            not _ADDRESS.fullmatch(result.payer or "") or result.payer.lower()!=verified_payer):
            raise RuntimeError("facilitator settlement response ambiguous")
        # SDK 2.17 SettleResponse proves facilitator acceptance and identifies a
        # transaction, but contains no chain receipt/block/finality timestamp.
        # Therefore this adapter cannot manufacture `finality_at` from local time;
        # a separately authenticated receipt/finality reconciler must promote it.
        raise RuntimeError("settlement accepted but receipt finality is unavailable; reconciliation required")
