"""Auditable external Ed25519 signer ceremony and monotonic claim seams."""
from __future__ import annotations
import hashlib, hmac, json, re, threading
from datetime import datetime, timezone
from typing import Any, Protocol
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PURPOSE="growthmap-license-authority-signing"
DOMAIN="growthmap-activation-certificate-v2"
FIELDS={"schema_version","purpose","domain","algorithm","authority_id","key_id","generation","activated_at","predecessor_generation","public_key_sha256","provider_attestation_id"}
CLAIM_FIELDS={"generation","ceremony_sha256"}

class Ed25519SignerProvider(Protocol):
    """Opaque provider: signatures are its sole output; private bytes are not exportable."""
    def sign(self,message:bytes)->bytes: ...

class SignerGenerationAnchor(Protocol):
    """Atomically binds a generation to one immutable canonical ceremony digest."""
    def read(self)->dict[str,Any]: ...
    def compare_and_advance(self,expected:dict[str,Any],new:dict[str,Any])->dict[str,Any]: ...

def validate_anchor_claim(value:Any,*,allow_zero:bool=True)->dict[str,Any]:
    if type(value) is not dict or set(value)!=CLAIM_FIELDS:raise ValueError("invalid_anchor_claim")
    generation=value["generation"];digest=value["ceremony_sha256"]
    if type(generation) is not int or generation<0 or (not allow_zero and generation<1):raise ValueError("invalid_anchor_claim")
    if generation==0:
        if digest is not None:raise ValueError("invalid_anchor_claim")
    elif type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}",digest):raise ValueError("invalid_anchor_claim")
    return {"generation":generation,"ceremony_sha256":digest}

class OfflineFixtureMonotonicAnchor:
    """Explicit process-local offline fixture; never production wiring."""
    def __init__(self,generation:int=0,ceremony_sha256:str|None=None):
        self._claim=validate_anchor_claim({"generation":generation,"ceremony_sha256":ceremony_sha256});self._lock=threading.Lock();self.available=True
    def read(self)->dict[str,Any]:
        with self._lock:
            if not self.available:raise RuntimeError("fixture_anchor_unavailable")
            return dict(self._claim)
    def compare_and_advance(self,expected:dict[str,Any],new:dict[str,Any])->dict[str,Any]:
        expected=validate_anchor_claim(expected);new=validate_anchor_claim(new,allow_zero=False)
        with self._lock:
            if not self.available:raise RuntimeError("fixture_anchor_unavailable")
            if self._claim==new:return dict(self._claim)
            if self._claim!=expected or new["generation"]!=expected["generation"]+1:raise RuntimeError("fixture_anchor_conflict")
            self._claim=dict(new);return dict(self._claim)

def canonical(value:dict[str,Any])->bytes:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def validate(descriptor:Any,reviewed_public_key:bytes,now:datetime):
    if type(descriptor) is not dict or set(descriptor)!=FIELDS:raise ValueError("invalid_ceremony_schema")
    if type(descriptor["schema_version"]) is not int or descriptor["schema_version"]!=1:raise ValueError("invalid_ceremony_schema_version")
    if descriptor["purpose"]!=PURPOSE or descriptor["domain"]!=DOMAIN or descriptor["algorithm"]!="Ed25519":raise ValueError("invalid_ceremony_binding")
    if type(descriptor["authority_id"]) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}",descriptor["authority_id"]):raise ValueError("invalid_authority_id")
    if type(descriptor["key_id"]) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}",descriptor["key_id"]):raise ValueError("invalid_key_id")
    g=descriptor["generation"];p=descriptor["predecessor_generation"]
    if type(g) is not int or g<1:raise ValueError("invalid_generation")
    if (g==1 and p is not None) or (g>1 and (type(p) is not int or p!=g-1)):raise ValueError("invalid_predecessor")
    value=descriptor["activated_at"]
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z",value):raise ValueError("invalid_activation_time")
    try:activated=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as error:raise ValueError("invalid_activation_time") from error
    if activated.isoformat(timespec="microseconds" if activated.microsecond else "seconds").replace("+00:00","Z")!=value:raise ValueError("invalid_activation_time")
    if not isinstance(now,datetime) or now.tzinfo is None:raise RuntimeError("invalid_authority_clock")
    if activated>now.astimezone(timezone.utc):raise ValueError("ceremony_not_active")
    digest=descriptor["public_key_sha256"]
    if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}",digest):raise ValueError("invalid_public_key_hash")
    if type(reviewed_public_key) is not bytes or not hmac.compare_digest(hashlib.sha256(reviewed_public_key).hexdigest(),digest):raise ValueError("public_key_hash_mismatch")
    try:
        try:public=serialization.load_pem_public_key(reviewed_public_key)
        except ValueError:public=serialization.load_der_public_key(reviewed_public_key)
    except Exception as error:raise ValueError("invalid_public_key") from error
    if not isinstance(public,Ed25519PublicKey):raise ValueError("public_key_must_be_ed25519")
    a=descriptor["provider_attestation_id"]
    if type(a) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}",a):raise ValueError("invalid_attestation")
    return dict(descriptor),public,canonical(descriptor)
