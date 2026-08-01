"""Fail-closed adapter around the official x402 Python SDK 2.17.0."""
from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from .service import BASE_NETWORK, BASE_USDC

_TX = re.compile(r"0x[0-9a-fA-F]{64}")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")

class OfficialX402Facilitator:
    """Synchronous boundary used by the durable ledger.

    ``client`` is injectable only to permit offline contract tests. Production
    construction uses x402.http.HTTPFacilitatorClientSync.
    """
    def __init__(self, endpoint: str, *, timeout: float = 20.0, client: Any = None, allowed_origin: str|None=None, context_ttl=120, max_contexts=1024):
        parsed=urlsplit(endpoint);origin=f"{parsed.scheme}://{parsed.netloc}"
        if (parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in("","/") or
            (allowed_origin is not None and origin.lower()!=allowed_origin.rstrip('/').lower())):
            raise RuntimeError("facilitator endpoint must be an exact allowed HTTPS origin")
        self.endpoint = origin
        if client is None:
            from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync
            client = HTTPFacilitatorClientSync(FacilitatorConfig(url=self.endpoint, timeout=timeout))
        self.client = client
        self._contexts: dict[str, tuple[Any, Any,str,float]] = {};self._lock=threading.Lock();self.context_ttl=context_ttl;self.max_contexts=max_contexts

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
