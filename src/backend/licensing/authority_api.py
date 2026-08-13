"""Dependency-injected, source-only Authority ASGI boundary.

TLS and client-certificate validation terminate at a reviewed edge. ``PeerDescriptor`` is only
an injected assertion from that edge; it is not application-level proof of a TLS handshake.
Production composition additionally requires reviewed identity providers, an atomic durable
replay store, and an external rollback-resistant monotonic anchor. This module never reads
production configuration or constructs those dependencies from the environment.

The request checks here are defense in depth *after* the ASGI server/parser has accepted and
allocated the request. Production must independently configure parser-level limits at the edge
and ASGI server for header count, name/value and aggregate sizes, body size, duplicate
Content-Length, and Content-Length/Transfer-Encoding conflicts. This app cannot provide
pre-parser enforcement. It deliberately accepts only ASCII header values and rejects every CTL
(including HTAB), obs-text, and Transfer-Encoding at this fixed-length JSON boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from .gift_service import GiftLicenseService

MAX_BODY_BYTES = 16_384
MAX_HEADER_COUNT = 64
MAX_HEADER_NAME_BYTES = 64
MAX_HEADER_VALUE_BYTES = 4_096
MAX_HEADER_BYTES = 16_384
MAX_JSON_DEPTH = 8
MAX_JSON_NODES = 128
MAX_JSON_CONTAINER_ENTRIES = 32
MAX_STRING_BYTES = 4_096
MAX_INTEGER_MAGNITUDE = 2**63 - 1
NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")

AuthorityId = Annotated[str, StringConstraints(strict=True, pattern=r"[a-z0-9][a-z0-9_-]{2,63}")]
KeyId = Annotated[str, StringConstraints(strict=True, pattern=r"[a-z0-9][a-z0-9._-]{2,63}")]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"[a-f0-9]{64}")]
Attestation = Annotated[str, StringConstraints(strict=True, pattern=r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")]
Source = Annotated[str, StringConstraints(strict=True, pattern=r"[a-z][a-z0-9_-]{0,31}")]
LicenseId = Annotated[str, StringConstraints(strict=True, pattern=r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")]
DeviceId = Annotated[str, StringConstraints(strict=True, pattern=r"gmdev_[a-f0-9]{64}")]
DevicePublicKey = Annotated[str, StringConstraints(strict=True, min_length=40, max_length=64, pattern=r"[A-Za-z0-9+/]+={0,2}")]
ClaimKey = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"[A-Za-z0-9._-]+")]
ChallengeId = Annotated[str, StringConstraints(strict=True, pattern=r"gmc_[a-f0-9]{32}")]
Proof = Annotated[str, StringConstraints(strict=True, min_length=80, max_length=128, pattern=r"[A-Za-z0-9+/]+={0,2}")]
CanonicalTimestamp = Annotated[str, StringConstraints(strict=True, min_length=20, max_length=32, pattern=r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")]
UtcTimestamp = Annotated[str, StringConstraints(strict=True, min_length=20, max_length=32, pattern=r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")]
TxHash = Annotated[str, StringConstraints(strict=True, pattern=r"0x[a-fA-F0-9]{64}")]
EncodedSignature = Annotated[str, StringConstraints(strict=True, min_length=80, max_length=128, pattern=r"[A-Za-z0-9+/]+={0,2}")]
Nonce = Annotated[str, StringConstraints(strict=True, pattern=r"[A-Za-z0-9_-]{16,128}")]
ActivationId = Annotated[str, StringConstraints(strict=True, pattern=r"gma_[a-f0-9]{32}")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _validate_utc_timestamp(value: str) -> str:
    """Validate exact UTC RFC3339 syntax without rewriting signed payload text."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid UTC timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("invalid UTC timestamp")
    return value


class SignerIdentity(StrictModel):
    authority_id: AuthorityId
    key_id: KeyId
    generation: Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]
    public_key_sha256: Digest
    attestation: Attestation


class HealthDescriptor(StrictModel):
    """Minimal public identity; signer attestation stays on authenticated service receipts."""
    authority_id: AuthorityId
    key_id: KeyId
    generation: Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]
    public_key_sha256: Digest
    status: Literal["active"]

class ProductionHealthDescriptor(HealthDescriptor):
    # Injected by source construction, never read from mutable Authority configuration.
    release_sha256: Digest


class ActivationChallengeBody(StrictModel):
    license_id: LicenseId
    device_public_key: DevicePublicKey


class ServiceActivationChallengeBody(ActivationChallengeBody):
    """Payments-only activation input authenticated by the signed service edge."""


class ServiceActivationCompleteBody(StrictModel):
    # Kept structurally separate so service routes cannot accidentally acquire public fields.
    challenge_id: ChallengeId
    proof: Proof

class ServiceRefreshChallengeBody(StrictModel):
    activation_id: ActivationId
    license_id: LicenseId
    device_public_key: DevicePublicKey

class ServiceGiftRefreshChallengeBody(ServiceRefreshChallengeBody):
    """No portable Gift secret: provenance is resolved by license_id inside Authority."""

class ServiceRefreshCompleteBody(StrictModel):
    challenge_id: Annotated[str, StringConstraints(strict=True, pattern=r"gmr_[a-f0-9]{32}")]
    proof: Proof


class GiftChallengeBody(StrictModel):
    claim_key: ClaimKey
    device_public_key: DevicePublicKey


class ServiceGiftCreateBody(StrictModel):
    edition: Literal["personal", "pro", "studio"] = "personal"
    major_version: Literal[1] = 1
    seat_limit: Literal[1, 2] = 2
    expires_at: None = None
    check_in_days: Annotated[int, Field(strict=True, ge=1, le=365)] = 30


class ServiceGiftIdBody(StrictModel):
    gift_id: Annotated[str, StringConstraints(strict=True, pattern=r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")]


class ServiceGiftDeviceBody(ServiceGiftIdBody):
    device_id: DeviceId


class CompleteBody(StrictModel):
    challenge_id: ChallengeId
    proof: Proof


class DeactivateBody(StrictModel):
    license_id: LicenseId
    device_id: DeviceId


class EntitlementBody(StrictModel):
    source: Source
    source_id: Digest
    payload_digest: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    edition: Literal["personal", "pro", "studio"] = "personal"
    major_version: Literal[1] = 1
    seat_limit: Literal[1, 2] = 2


class EntitlementReadBody(StrictModel):
    source: Source
    source_id: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity


class RevocationBody(StrictModel):
    source: Source
    source_id: Digest
    payload_digest: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    license_id: LicenseId
    action: Literal["refund", "revoke"]
    reason: Literal["refund", "chargeback", "fraud", "terms_violation", "administrative"]
    payment_proof: Digest
    tx_hash: TxHash
    created_at: UtcTimestamp

    _created_at_utc = field_validator("created_at")(_validate_utc_timestamp)


class Challenge(StrictModel):
    challenge_id: ChallengeId
    nonce: Nonce
    license_id: LicenseId
    device_public_key: DevicePublicKey


class ChallengeResponse(StrictModel):
    state: Literal["challenge_issued"]
    challenge: Challenge

class RefreshChallenge(StrictModel):
    challenge_id: Annotated[str, StringConstraints(strict=True, pattern=r"gmr_[a-f0-9]{32}")]
    activation_id: ActivationId
    nonce: Nonce
    license_id: LicenseId
    device_public_key: DevicePublicKey

class RefreshChallengeResponse(StrictModel):
    state: Literal["challenge_issued"]
    challenge: RefreshChallenge


class Certificate(StrictModel):
    schema_version: Literal[2]
    certificate_type: Literal["growthmap_device_activation"]
    product: Literal["growthmap"]
    edition: Literal["personal", "pro", "studio"]
    license_id: LicenseId
    activation_id: ActivationId
    major_version: Literal[1]
    device_allowance: Literal[1, 2]
    device_id: DeviceId
    device_public_key: DevicePublicKey
    issued_at: CanonicalTimestamp
    expires_at: CanonicalTimestamp | None
    revoked_at: CanonicalTimestamp | None
    max_active_projects: Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)] | None
    next_check_in_at: CanonicalTimestamp
    signature: EncodedSignature


class ActivationResponse(StrictModel):
    state: Literal["activated"]
    certificate: Certificate


class EntitlementAcknowledgement(StrictModel):
    license_id: LicenseId
    edition: Literal["personal", "pro", "studio"]
    major_version: Literal[1]
    device_allowance: Literal[1, 2]
    delivery_receipt: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    ack_signature: EncodedSignature


class EntitlementReadback(StrictModel):
    source: Source
    source_id: Digest
    payload_digest: Digest
    license_id: LicenseId
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    delivery_receipt: Digest
    ack_signature: EncodedSignature


class RevocationAcknowledgement(StrictModel):
    license_id: LicenseId
    revoked_at: CanonicalTimestamp
    revocation_receipt: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    ack_signature: EncodedSignature


class RevocationReadback(StrictModel):
    source: Source
    source_id: Digest
    payload_digest: Digest
    license_id: LicenseId
    action: Literal["refund", "revoke"]
    reason: Literal["refund", "chargeback", "fraud", "terms_violation", "administrative"]
    payment_proof: Digest
    tx_hash: TxHash
    created_at: UtcTimestamp
    revoked_at: CanonicalTimestamp

    _created_at_utc = field_validator("created_at")(_validate_utc_timestamp)
    request_digest: Digest
    revocation_receipt: Digest
    authority_id: AuthorityId
    signer_identity: SignerIdentity
    ack_signature: EncodedSignature


class DeactivationResponse(StrictModel):
    deactivated: bool


@dataclass(frozen=True)
class PeerDescriptor:
    """Trusted edge assertion seam; construction alone does not authenticate TLS."""
    identity: str
    source: str = "trusted-edge"


@dataclass(frozen=True)
class ServiceAuthRequest:
    method: str
    path: str
    body_sha256: str
    timestamp: str
    nonce: str
    audience: str
    authority_id: str
    credential: bytes
    peer: PeerDescriptor | None


@dataclass(frozen=True)
class ServiceIdentity:
    subject: str
    audience: str
    authority_id: str


@dataclass(frozen=True)
class OwnerAuthorization:
    subject: str
    role: str
    license_id: str
    device_id: str


@runtime_checkable
class ServiceIdentityVerifier(Protocol):
    def verify(self, request: ServiceAuthRequest) -> ServiceIdentity | None: ...


@runtime_checkable
class ReplayStore(Protocol):
    """Legacy staging replay seam; production composition uses RequestJournal."""
    def consume(self, subject: str, nonce: str, timestamp: str) -> bool: ...


@runtime_checkable
class RequestJournal(Protocol):
    """Durably bind a complete authenticated request and recover its deterministic result."""
    production_safe: bool
    fixture: bool
    process_local: bool
    def execute(self, request: ServiceAuthRequest, identity: ServiceIdentity, operation): ...
    def close(self) -> None: ...


@runtime_checkable
class OwnerAuthorizationVerifier(Protocol):
    def authorize(self, *, credential: bytes, method: str, path: str, body_sha256: str,
                  peer: PeerDescriptor | None, license_id: str, device_id: str) -> OwnerAuthorization | None: ...


@runtime_checkable
class SignerDescriptorProvider(Protocol):
    def descriptor(self) -> dict[str, Any] | None: ...


@runtime_checkable
class MonotonicAnchorVerifier(Protocol):
    def verify(self, descriptor: dict[str, Any]) -> bool: ...


def _detail(status: int) -> str:
    if status == 503 or status >= 500:
        return "service unavailable"
    if status in (401, 403):
        return "request denied"
    if status in (400, 405, 413, 422):
        return "invalid request"
    return "resource unavailable"


def _error(status: int) -> HTTPException:
    return HTTPException(status, _detail(status))


def _secured_response(status: int, detail: str | None = None) -> JSONResponse:
    response = JSONResponse({"detail": detail or _detail(status)}, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


_TCHAR = frozenset(b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _raw_headers(request: Request) -> dict[bytes, bytes]:
    """Validate the raw ASGI representation; this is not a pre-parser resource limit."""
    rows = request.scope.get("headers") or []
    if type(rows) is not list or len(rows) > MAX_HEADER_COUNT:
        raise _error(400)
    total = 0
    result: dict[bytes, bytes] = {}
    seen: set[bytes] = set()
    for name, value in rows:
        if type(name) is not bytes or type(value) is not bytes:
            raise _error(400)
        total += len(name) + len(value)
        if (not name or len(name) > MAX_HEADER_NAME_BYTES or len(value) > MAX_HEADER_VALUE_BYTES
                or total > MAX_HEADER_BYTES or any(byte not in _TCHAR for byte in name)
                or any(byte < 0x20 or byte >= 0x7f for byte in value)):
            raise _error(400)
        lowered = name.lower()
        if lowered in seen:  # includes differently-cased raw-name collisions
            raise _error(400)
        seen.add(lowered)
        result[lowered] = value
    # Header syntax and duplicate-name rejection are global. Framing semantics are enforced
    # by the method/route body policy below, after raw tuples have survived this parser.
    return result


def _path(request: Request) -> str:
    raw = request.scope.get("raw_path")
    if not isinstance(raw, bytes) or not raw or len(raw) > 256:
        raise _error(400)
    try:
        path = raw.decode("ascii", "strict")
    except UnicodeError:
        raise _error(400) from None
    if path != request.url.path:
        raise _error(400)
    return path


def _walk_json(value: Any, *, depth: int = 1, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    if depth > MAX_JSON_DEPTH:
        raise ValueError("depth")
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        raise ValueError("nodes")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_INTEGER_MAGNITUDE:
            raise ValueError("integer")
        return
    if type(value) is float:  # no Authority schema admits floating-point input
        raise ValueError("float")
    if type(value) is str:
        if len(value.encode("utf-8", "strict")) > MAX_STRING_BYTES:
            raise ValueError("string")
        return
    if type(value) is list:
        if len(value) > MAX_JSON_CONTAINER_ENTRIES:
            raise ValueError("list")
        for item in value:
            _walk_json(item, depth=depth + 1, counter=counter)
        return
    if type(value) is dict:
        if len(value) > MAX_JSON_CONTAINER_ENTRIES:
            raise ValueError("dict")
        for key, item in value.items():
            if type(key) is not str or not key.isascii() or unicodedata.normalize("NFC", key) != key:
                raise ValueError("key")
            _walk_json(item, depth=depth + 1, counter=counter)
        return
    raise ValueError("type")


def _canonical_content_length(headers: dict[bytes, bytes]) -> int | None:
    raw_length = headers.get(b"content-length")
    if raw_length is None:
        return None
    # Bound digit count before conversion so a parser-accepted adversarial value cannot cause
    # an unbounded integer conversion here. Canonical decimal excludes signs and leading zeroes.
    if (not re.fullmatch(rb"(?:0|[1-9][0-9]*)", raw_length)
            or len(raw_length) > len(str(MAX_BODY_BYTES))):
        raise _error(400)
    return int(raw_length)


async def _body(request: Request, model: type[BaseModel], headers: dict[bytes, bytes]) -> tuple[BaseModel, bytes, str]:
    # Mutation routes are fixed-length-or-ASGI-stream JSON. Transfer-Encoding has no contract.
    if b"transfer-encoding" in headers:
        raise _error(400)
    declared_length = _canonical_content_length(headers)
    if declared_length is not None and declared_length > MAX_BODY_BYTES:
        raise _error(413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _error(413)
        chunks.append(chunk)
    raw = b"".join(chunks)
    if declared_length is not None and declared_length != len(raw):
        raise _error(400)
    if not raw:
        raise _error(400)

    def pairs(items):
        output: dict[str, Any] = {}
        folded: set[str] = set()
        for key, value in items:
            if type(key) is not str:
                raise ValueError("key")
            normalized = unicodedata.normalize("NFC", key)
            collision = normalized.casefold()
            if not key.isascii() or normalized != key or collision in folded:
                raise ValueError("duplicate/confusable key")
            folded.add(collision)
            output[key] = value
        return output

    def reject_constant(_value):
        raise ValueError("non-finite")

    try:
        decoded = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
        _walk_json(decoded)
        value = model.model_validate(decoded)
    except (UnicodeError, ValueError, ValidationError, json.JSONDecodeError, RecursionError, OverflowError):
        raise _error(400) from None
    return value, raw, hashlib.sha256(raw).hexdigest()


def _ascii(headers: dict[bytes, bytes], name: bytes) -> str:
    raw = headers.get(name)
    if raw is None or not raw:
        raise _error(403)
    try:
        return raw.decode("ascii", "strict")
    except UnicodeError:
        raise _error(403) from None


def _aware_now(now) -> datetime:
    try:
        value = now()
    except Exception:
        raise _error(503) from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error(503)
    return value.astimezone(timezone.utc)


_ROUTE_POLICY_UNSET = object()


def create_authority_app(
    *, authority, gift_service: GiftLicenseService | None = None,
    service_verifier: ServiceIdentityVerifier | None = None,
    replay_store: ReplayStore | None = None,
    request_journal: RequestJournal | None = None,
    owner_verifier: OwnerAuthorizationVerifier | None = None,
    signer_descriptor_provider: SignerDescriptorProvider | None = None,
    anchor_verifier: MonotonicAnchorVerifier | None = None,
    peer_resolver=None, production: bool = False,
    service_audience: str = "growthmap-authority",
    max_clock_skew_seconds: int = 300,
    now=lambda: datetime.now(timezone.utc),
    expose_schema_for_tests: bool = False,
    route_policy=_ROUTE_POLICY_UNSET,
    release_sha256: str | None = None,
) -> FastAPI:
    """Compose only from explicit providers; never read environment state.

    Production omission irreversibly selects ``service-only`` and production accepts no
    other explicit value. Only non-production/local composition defaults to ``all``.
    """
    if type(production) is not bool or type(expose_schema_for_tests) is not bool:
        raise RuntimeError("authority composition invalid")
    if release_sha256 is not None and (type(release_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", release_sha256) is None):
        raise RuntimeError("authority release identity invalid")
    if route_policy is _ROUTE_POLICY_UNSET:
        route_policy = "service-only" if production else "all"
    elif type(route_policy) is not str:
        raise RuntimeError("authority composition invalid")
    if (authority is None or route_policy not in {"all", "service-only"}
            or (production and route_policy != "service-only")
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", service_audience or "")):
        raise RuntimeError("authority composition invalid")
    if type(max_clock_skew_seconds) is not int or not 1 <= max_clock_skew_seconds <= 900:
        raise RuntimeError("authority composition invalid")
    if production and expose_schema_for_tests:
        raise RuntimeError("production Authority schema exposure forbidden")
    if production and (service_verifier is None or request_journal is None or owner_verifier is None
                       or signer_descriptor_provider is None or anchor_verifier is None):
        raise RuntimeError("production Authority dependencies unavailable")
    if production and any(
        getattr(provider, "production_safe", False) is not True
        or getattr(provider, "fixture", True)
        or getattr(provider, "process_local", False)
        for provider in (service_verifier, request_journal, owner_verifier,
                         signer_descriptor_provider, anchor_verifier)
    ):
        raise RuntimeError("production Authority provider unsafe")
    if production and replay_store is not None:
        raise RuntimeError("production legacy replay provider forbidden")
    try:
        _aware_now(now)
    except HTTPException as error:
        raise RuntimeError("authority clock unavailable") from error
    # The closed production surface never constructs the excluded Gift provider.
    gifts = (gift_service or GiftLicenseService(authority)) if route_policy == "all" else None
    app = FastAPI(
        title="GrowthMap Authority Candidate", version="2-source-only",
        docs_url="/docs" if expose_schema_for_tests else None,
        redoc_url="/redoc" if expose_schema_for_tests else None,
        openapi_url="/openapi.json" if expose_schema_for_tests else None,
        redirect_slashes=False,
    )

    def peer(request: Request) -> PeerDescriptor | None:
        if peer_resolver is None:
            return None
        try:
            value = peer_resolver(request)
        except Exception:
            raise _error(403) from None
        if (not isinstance(value, PeerDescriptor) or not value.identity or not value.identity.isascii()
                or len(value.identity.encode()) > 256 or not value.source or not value.source.isascii()
                or len(value.source.encode()) > 64):
            raise _error(403)
        return value

    def descriptor() -> SignerIdentity:
        if signer_descriptor_provider is None:
            raise _error(503)
        try:
            supplied = signer_descriptor_provider.descriptor()
            if type(supplied) is not dict or set(supplied) != set(SignerIdentity.model_fields) | {"status"}:
                raise ValueError
            if supplied["status"] != "active":
                raise ValueError
            identity = SignerIdentity.model_validate({k: supplied[k] for k in SignerIdentity.model_fields})
            handshake = SignerIdentity.model_validate(authority.handshake())
        except HTTPException:
            raise
        except Exception:
            raise _error(503) from None
        if identity != handshake:
            raise _error(503)
        if anchor_verifier is None:
            if production:
                raise _error(503)
        else:
            try:
                if anchor_verifier.verify(identity.model_dump() | {"status": "active"}) is not True:
                    raise _error(503)
            except HTTPException:
                raise
            except Exception:
                raise _error(503) from None
        return identity

    def bind_body_identity(value: EntitlementBody | EntitlementReadBody | RevocationBody, current: SignerIdentity) -> None:
        # Semantic signer binding intentionally precedes credential verification and replay
        # consumption, so malformed/stale signer identities cannot burn a valid nonce.
        if value.signer_identity != current:
            raise _error(403)
        if value.authority_id != current.authority_id:
            raise _error(403)

    def service_auth(request: Request, digest: str, headers: dict[bytes, bytes], path: str) -> tuple[ServiceIdentity, ServiceAuthRequest]:
        if service_verifier is None or (replay_store is None and request_journal is None):
            raise _error(503)
        timestamp = _ascii(headers, b"x-authority-timestamp")
        nonce = _ascii(headers, b"x-authority-nonce")
        audience = _ascii(headers, b"x-authority-audience")
        authority_id = _ascii(headers, b"x-authority-id")
        credential = headers.get(b"x-authority-service-auth")
        if (credential is None or not credential or not NONCE_RE.fullmatch(nonce)
                or audience != service_audience or authority_id != authority.authority_id):
            raise _error(403)
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if (parsed.tzinfo is None or parsed.utcoffset() is None
                    or abs((_aware_now(now) - parsed.astimezone(timezone.utc)).total_seconds()) > max_clock_skew_seconds):
                raise ValueError
        except HTTPException:
            raise
        except Exception:
            raise _error(403) from None
        assertion = ServiceAuthRequest(request.method, path, digest, timestamp, nonce, audience,
                                       authority_id, credential, peer(request))
        try:
            identity = service_verifier.verify(assertion)
        except Exception:
            raise _error(403) from None
        if (not isinstance(identity, ServiceIdentity) or identity.audience != audience
                or identity.authority_id != authority_id or not identity.subject
                or not identity.subject.isascii() or len(identity.subject.encode()) > 128):
            raise _error(403)
        if request_journal is None:
            try:
                fresh = replay_store.consume(identity.subject, nonce, timestamp)
            except Exception:
                raise _error(503) from None
            if fresh is not True:
                raise _error(403)
        return identity, assertion

    def owner_auth(request: Request, digest: str, headers: dict[bytes, bytes], value: DeactivateBody, path: str) -> OwnerAuthorization:
        descriptor()
        if owner_verifier is None:
            raise _error(503)
        credential = headers.get(b"authorization")
        if credential is None or not credential:
            raise _error(403)
        try:
            result = owner_verifier.authorize(credential=credential, method=request.method, path=path,
                body_sha256=digest, peer=peer(request), license_id=value.license_id, device_id=value.device_id)
        except Exception:
            raise _error(403) from None
        if (not isinstance(result, OwnerAuthorization) or result.role not in {"owner", "admin"}
                or result.license_id != value.license_id or result.device_id != value.device_id or not result.subject
                or not result.subject.isascii() or len(result.subject.encode()) > 128):
            raise _error(403)
        return result

    @app.exception_handler(StarletteHTTPException)
    async def generic_http(_request: Request, error: StarletteHTTPException):
        return _secured_response(error.status_code)

    @app.exception_handler(RequestValidationError)
    async def generic_request_validation(_request: Request, _error_value: RequestValidationError):
        return _secured_response(422)

    @app.exception_handler(ResponseValidationError)
    async def generic_response_validation(_request: Request, _error_value: ResponseValidationError):
        return _secured_response(500)

    @app.exception_handler(ValidationError)
    async def generic_validation(_request: Request, _error_value: ValidationError):
        return _secured_response(400)

    @app.exception_handler(Exception)
    async def generic_exception(_request: Request, _error_value: Exception):
        # Deliberately do not log request bodies, proofs, capabilities, or provider exceptions.
        return _secured_response(500)

    @app.middleware("http")
    async def bounded_generic_boundary(request: Request, call_next):
        try:
            headers = _raw_headers(request)
            # GET/HEAD routes in this boundary are bodyless. TestClient commonly supplies a
            # canonical CL=0; accept it (and absence), while rejecting framing that advertises a
            # body. No body read is needed, avoiding an unnecessary receive-side effect.
            if request.method in {"GET", "HEAD"}:
                declared = _canonical_content_length(headers)
                if declared not in {None, 0} or b"transfer-encoding" in headers:
                    raise _error(400)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.scope.get("query_string", b""):
                raise _error(400)
            response = await call_next(request)
        except HTTPException as error:
            response = _secured_response(error.status_code)
        except Exception:
            response = _secured_response(500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/v1/authority/identity", response_model=ProductionHealthDescriptor if release_sha256 is not None else HealthDescriptor)
    async def identity():
        current = descriptor()
        result={"authority_id": current.authority_id, "key_id": current.key_id,
                "generation": current.generation, "public_key_sha256": current.public_key_sha256,
                "status": "active"}
        if release_sha256 is not None:result["release_sha256"]=release_sha256
        return result

    async def activation(request: Request):
        headers = _raw_headers(request); value, _, _ = await _body(request, ActivationChallengeBody, headers)
        descriptor()
        try:
            return {"state": "challenge_issued", "challenge": authority.issue_activation_challenge(**value.model_dump())}
        except Exception:
            raise _error(404) from None

    async def activation_complete(request: Request):
        headers = _raw_headers(request); value, _, _ = await _body(request, CompleteBody, headers)
        descriptor()
        try:
            return {"state": "activated", "certificate": authority.activate_challenge(**value.model_dump(), expected_flow_kind="payment")}
        except Exception:
            raise _error(404) from None

    async def gift_challenge(request: Request):
        headers = _raw_headers(request); value, _, _ = await _body(request, GiftChallengeBody, headers)
        descriptor()
        try:
            return {"state": "challenge_issued", "challenge": gifts.challenge(value.claim_key, value.device_public_key)}
        except Exception:
            raise _error(404) from None

    async def gift_complete(request: Request):
        headers = _raw_headers(request); value, _, _ = await _body(request, CompleteBody, headers)
        descriptor()
        try:
            return {"state": "activated", "certificate": gifts.complete(value.challenge_id, value.proof)}
        except Exception:
            raise _error(404) from None

    def service_preflight(request: Request, value, digest: str, headers: dict[bytes, bytes]):
        path = _path(request)
        current = descriptor()
        if isinstance(value, (EntitlementBody, EntitlementReadBody, RevocationBody)):
            bind_body_identity(value, current)
        return service_auth(request, digest, headers, path)

    def service_execute(authenticated, operation):
        if request_journal is None:
            return operation()
        identity, assertion = authenticated
        try:
            return request_journal.execute(assertion, identity, operation)
        except Exception:
            raise _error(503) from None

    @app.post("/v1/service/entitlements", response_model=EntitlementAcknowledgement)
    async def entitlement(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, EntitlementBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: authority.create_external_entitlement(**value.model_dump()))
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/entitlements/read", response_model=EntitlementReadback)
    async def entitlement_read(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, EntitlementReadBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: authority.read_external_entitlement_acknowledgement(**value.model_dump(exclude={"authority_id"})))
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/revocations", response_model=RevocationAcknowledgement)
    async def revocation(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, RevocationBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: authority.revoke_external_entitlement(**value.model_dump()))
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/revocations/read", response_model=RevocationReadback)
    async def revocation_read(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, EntitlementReadBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: authority.read_external_revocation_acknowledgement(**value.model_dump(exclude={"authority_id"})))
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/activation/challenge", response_model=ChallengeResponse)
    async def service_activation_challenge(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, ServiceActivationChallengeBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: {"state": "challenge_issued", "challenge": authority.issue_activation_challenge(**value.model_dump())})
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/activation/complete", response_model=ActivationResponse)
    async def service_activation_complete(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, ServiceActivationCompleteBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: {"state": "activated", "certificate": authority.activate_challenge(**value.model_dump(), expected_flow_kind="payment")})
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/activation/refresh/challenge", response_model=RefreshChallengeResponse)
    async def service_activation_refresh_challenge(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, ServiceRefreshChallengeBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:return service_execute(authenticated, lambda: {"state":"challenge_issued","challenge":authority.issue_activation_refresh_challenge(**value.model_dump(),expected_flow_kind="payment")})
        except HTTPException:raise
        except Exception:raise _error(404) from None

    @app.post("/v1/service/activation/refresh/complete", response_model=ActivationResponse)
    async def service_activation_refresh_complete(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, ServiceRefreshCompleteBody, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:return service_execute(authenticated, lambda: {"state":"activated","certificate":authority.complete_activation_refresh(**value.model_dump(),expected_flow_kind="payment")})
        except HTTPException:raise
        except Exception:raise _error(404) from None

    async def service_gift(request: Request, model, operation):
        headers = _raw_headers(request); value, _, digest = await _body(request, model, headers)
        authenticated = service_preflight(request, value, digest, headers)
        try:
            return service_execute(authenticated, lambda: operation(value))
        except HTTPException:
            raise
        except Exception:
            raise _error(404) from None

    @app.post("/v1/service/gifts/create")
    async def service_gift_create(request: Request):
        return await service_gift(request, ServiceGiftCreateBody, lambda value: GiftLicenseService(authority).create(**value.model_dump()))

    @app.post("/v1/service/gifts/list")
    async def service_gift_list(request: Request):
        return await service_gift(request, StrictModel, lambda _value: {"gifts": GiftLicenseService(authority).list()})

    @app.post("/v1/service/gifts/get")
    async def service_gift_get(request: Request):
        return await service_gift(request, ServiceGiftIdBody, lambda value: GiftLicenseService(authority).get(value.gift_id))

    @app.post("/v1/service/gifts/recover")
    async def service_gift_recover(request: Request):
        return await service_gift(request, ServiceGiftIdBody, lambda value: GiftLicenseService(authority).rotate(value.gift_id))

    @app.post("/v1/service/gifts/revoke")
    async def service_gift_revoke(request: Request):
        return await service_gift(request, ServiceGiftIdBody, lambda value: GiftLicenseService(authority).revoke(value.gift_id))

    @app.post("/v1/service/gifts/devices")
    async def service_gift_devices(request: Request):
        return await service_gift(request, ServiceGiftIdBody, lambda value: {"devices": GiftLicenseService(authority).devices(value.gift_id)})

    @app.post("/v1/service/gifts/devices/deactivate")
    async def service_gift_deactivate(request: Request):
        return await service_gift(request, ServiceGiftDeviceBody, lambda value: {"deactivated": GiftLicenseService(authority).deactivate(value.gift_id, value.device_id)})

    @app.post("/v1/service/gifts/claim/challenge", response_model=ChallengeResponse)
    async def service_gift_claim_challenge(request: Request):
        return await service_gift(request, GiftChallengeBody, lambda value: {"state": "challenge_issued", "challenge": GiftLicenseService(authority).challenge(value.claim_key, value.device_public_key)})

    @app.post("/v1/service/gifts/claim/complete", response_model=ActivationResponse)
    async def service_gift_claim_complete(request: Request):
        return await service_gift(request, CompleteBody, lambda value: {"state": "activated", "certificate": GiftLicenseService(authority).complete(value.challenge_id, value.proof)})

    @app.post("/v1/service/gifts/refresh/challenge", response_model=RefreshChallengeResponse)
    async def service_gift_refresh_challenge(request: Request):
        return await service_gift(request, ServiceGiftRefreshChallengeBody, lambda value: {"state":"challenge_issued","challenge":GiftLicenseService(authority).refresh_challenge(value.activation_id,value.license_id,value.device_public_key)})

    @app.post("/v1/service/gifts/refresh/complete", response_model=ActivationResponse)
    async def service_gift_refresh_complete(request: Request):
        return await service_gift(request, ServiceRefreshCompleteBody, lambda value: {"state":"activated","certificate":GiftLicenseService(authority).refresh_complete(value.challenge_id,value.proof)})

    async def deactivate(request: Request):
        headers = _raw_headers(request); value, _, digest = await _body(request, DeactivateBody, headers)
        owner_auth(request, digest, headers, value, _path(request))
        try:
            return {"deactivated": authority.deactivate(**value.model_dump())}
        except Exception:
            raise _error(404) from None

    if route_policy == "all":
        app.add_api_route("/v1/licenses/activation/challenge", activation, methods=["POST"], response_model=ChallengeResponse)
        app.add_api_route("/v1/licenses/activation/complete", activation_complete, methods=["POST"], response_model=ActivationResponse)
        app.add_api_route("/v1/gifts/claim/challenge", gift_challenge, methods=["POST"], response_model=ChallengeResponse)
        app.add_api_route("/v1/gifts/claim/complete", gift_complete, methods=["POST"], response_model=ActivationResponse)
        app.add_api_route("/v1/private/devices/deactivate", deactivate, methods=["POST"], response_model=DeactivationResponse)
    else:
        allowed=frozenset(("/v1/authority/identity","/v1/service/entitlements",
            "/v1/service/entitlements/read","/v1/service/revocations","/v1/service/revocations/read",
            "/v1/service/activation/challenge","/v1/service/activation/complete",
            "/v1/service/activation/refresh/challenge","/v1/service/activation/refresh/complete",
            "/v1/service/gifts/create","/v1/service/gifts/list","/v1/service/gifts/get",
            "/v1/service/gifts/recover","/v1/service/gifts/revoke","/v1/service/gifts/devices",
            "/v1/service/gifts/devices/deactivate","/v1/service/gifts/claim/challenge",
            "/v1/service/gifts/claim/complete","/v1/service/gifts/refresh/challenge",
            "/v1/service/gifts/refresh/complete"))
        @app.middleware("http")
        async def closed_production_route_surface(request: Request, call_next):
            # Exact decoded and raw path agreement prevents slash/percent/normalization aliases.
            raw=request.scope.get("raw_path",b"")
            try: raw_text=raw.decode("ascii","strict")
            except Exception: return _secured_response(404)
            if request.scope.get("path") not in allowed or raw_text not in allowed:
                return _secured_response(404)
            return await call_next(request)

    return app


create_authority_app.production_safe = True
create_authority_app.fixture = False
create_authority_app.process_local = False


def from_env(*_args, **_kwargs):
    raise RuntimeError("production Authority auto-composition is intentionally unavailable")
