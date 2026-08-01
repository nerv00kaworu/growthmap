"""Authenticated, fail-closed boundary for externally determined x402 finality."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .service import BASE_NETWORK, BASE_USDC

_DOMAIN = b"growthmap-authenticated-finality-v1\0"
_MAX_DOCUMENT = 16_384
_MAX_JSON_DEPTH = 32
_HASH = re.compile(r"[0-9a-f]{64}")
_TX = re.compile(r"0x[0-9a-f]{64}")
_ADDRESS = re.compile(r"0x[0-9a-f]{40}")
_LABEL = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,127}")
_CANONICAL_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00")
_FIELDS = {
    "outcome", "proof_hash", "nonce_hash", "order_id", "payer", "tx_hash",
    "evidence_hash", "source", "finality_at", "finality_basis", "network",
    "asset", "payee", "amount_minor",
}


class FinalityEvidenceProvider(Protocol):
    """Externally authorized provider. Returned bytes are still untrusted until MAC verification."""

    def finality_evidence(self, intent: dict[str, Any]) -> bytes: ...


def _strict_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    folded: set[str] = set()
    for key, value in items:
        if not isinstance(key, str) or key.casefold() in folded:
            raise ValueError("duplicate reconciliation field")
        folded.add(key.casefold())
        result[key] = value
    return result



def _reject_excessive_depth(value: Any, maximum: int = _MAX_JSON_DEPTH) -> None:
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > maximum:
            raise ValueError("invalid authenticated finality document")
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values() if isinstance(child, (dict, list)))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current if isinstance(child, (dict, list)))

def _parse_canonical_utc(raw: Any) -> datetime:
    """Parse the sole accepted UTC spelling: exactly ``datetime.isoformat()``."""
    if type(raw) is not str or not _CANONICAL_UTC.fullmatch(raw):
        raise ValueError
    parsed = datetime.fromisoformat(raw)
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError
    # isoformat emits no fraction for zero microseconds and exactly six digits
    # for a nonzero value, preventing equivalent re-signed clock spellings.
    if parsed.astimezone(timezone.utc).isoformat() != raw:
        raise ValueError
    return parsed


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_test_document(payload: dict[str, Any], key: bytes) -> bytes:
    """Build an authenticated fixture document. Test-only; never a production input loader."""
    mac = hmac.new(key, _DOMAIN + canonical_payload(payload), hashlib.sha256).hexdigest()
    return canonical_payload({"mac": mac, "payload": payload})


class AuthenticatedFinalityReconciler:
    """Normalize MAC-authenticated provider evidence into ``PaymentService``'s contract.

    HMAC uses the existing external settlement trust root with a distinct domain.
    The provider transport/object is not trusted; every security-relevant field is
    authenticated and then compared to the durable intent and configured merchant.
    """

    def __init__(
        self,
        provider: FinalityEvidenceProvider,
        mac_key: bytes,
        *,
        payee: str,
        network: str = BASE_NETWORK,
        asset: str = BASE_USDC,
        now: Callable[[], datetime] | None = None,
        max_document: int = _MAX_DOCUMENT,
    ):
        if not isinstance(mac_key, bytes) or len(mac_key) < 32:
            raise RuntimeError("authenticated finality MAC key missing/weak")
        if not _ADDRESS.fullmatch(payee.lower()):
            raise RuntimeError("authenticated finality payee invalid")
        if max_document < 512 or max_document > _MAX_DOCUMENT:
            raise RuntimeError("authenticated finality document bound invalid")
        self.provider = provider
        self._key = mac_key
        self.payee = payee.lower()
        self.network = network
        self.asset = asset.lower()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.max_document = max_document

    def reconcile(self, intent: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = self.provider.finality_evidence(dict(intent))
        except Exception as exc:
            raise ValueError("authenticated finality provider unavailable") from exc
        if not isinstance(raw, bytes) or not raw or len(raw) > self.max_document:
            raise ValueError("invalid authenticated finality document")
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("invalid authenticated finality document") from exc
        _reject_excessive_depth(document)
        if not isinstance(document, dict) or set(document) != {"mac", "payload"}:
            raise ValueError("invalid authenticated finality envelope")
        mac, payload = document["mac"], document["payload"]
        if not isinstance(mac, str) or not _HASH.fullmatch(mac) or not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError("invalid authenticated finality schema")
        expected = hmac.new(self._key, _DOMAIN + canonical_payload(payload), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("authenticated finality verification failed")
        self._validate(payload, intent)
        normalized = {key: payload[key] for key in (
            "outcome", "proof_hash", "nonce_hash", "order_id", "payer",
            "evidence_hash", "source", "finality_at", "finality_basis",
        )}
        if payload["outcome"] == "paid":
            normalized["tx_hash"] = payload["tx_hash"]
        return normalized

    def _validate(self, p: dict[str, Any], intent: dict[str, Any]) -> None:
        string_fields = _FIELDS - {"amount_minor"}
        if any(type(p[name]) is not str for name in string_fields) or type(p["amount_minor"]) is not int:
            raise ValueError("invalid authenticated finality field type")
        if p["outcome"] not in {"paid", "unpaid"}:
            raise ValueError("invalid authenticated finality outcome")
        if not all(_HASH.fullmatch(p[name]) for name in ("proof_hash", "nonce_hash", "evidence_hash")):
            raise ValueError("invalid authenticated finality digest")
        if not _ADDRESS.fullmatch(p["payer"]) or p["payer"] != p["payer"].lower():
            raise ValueError("invalid authenticated finality payer")
        if not _LABEL.fullmatch(p["source"]) or not _LABEL.fullmatch(p["finality_basis"]):
            raise ValueError("invalid authenticated finality attribution")
        paid = p["outcome"] == "paid"
        if (paid and not _TX.fullmatch(p["tx_hash"])) or (not paid and p["tx_hash"] != ""):
            raise ValueError("invalid authenticated finality transaction outcome")
        try:
            finality = _parse_canonical_utc(p["finality_at"])
            created = _parse_canonical_utc(intent.get("created_at"))
            now = self._now()
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid authenticated finality timestamp") from exc
        if (now.tzinfo is None or now.utcoffset() is None
                or finality < created or finality > now.astimezone(timezone.utc)):
            raise ValueError("invalid authenticated finality timestamp")
        bindings = {
            "proof_hash": intent.get("proof_hash"), "nonce_hash": intent.get("nonce_hash"),
            "order_id": intent.get("order_id"), "payer": intent.get("verified_payer"),
            "amount_minor": intent.get("amount_minor"), "network": self.network,
            "asset": self.asset, "payee": self.payee,
        }
        normalized = dict(p)
        normalized["payer"] = p["payer"].lower()
        normalized["asset"] = p["asset"].lower()
        normalized["payee"] = p["payee"].lower()
        if any(normalized[name] != expected for name, expected in bindings.items()):
            raise ValueError("authenticated finality binding mismatch")
