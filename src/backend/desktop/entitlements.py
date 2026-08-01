"""Desktop trial and signed entitlement policy.

No private signing material belongs in the product. Invalid/corrupt state always degrades to
extraction mode; it never affects access to existing data.
"""
from __future__ import annotations
import base64, json, os, re, tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TRIAL_DAYS = 7
TRIAL_ACTIVE_PROJECT_LIMIT = 2
CURRENT_MAJOR_VERSION = 1  # compiled product line; packaging preflight checks desktop metadata agreement
LICENSE_PATH = Path(os.getenv("GROWTHMAP_LICENSE_FILE", Path.home()/".growthmap"/"license.json"))
TRIAL_PATH = Path(os.getenv("GROWTHMAP_TRIAL_STATE_FILE", LICENSE_PATH.with_name("trial-state.json")))
REVOCATION_PATH = Path(os.getenv("GROWTHMAP_REVOCATION_FILE", LICENSE_PATH.with_name("revocation.json")))
def _public_key_path() -> Path:
    bundled=Path(__file__).with_name("license_public_key.pem")
    # Frozen/packaged builds receive a desktop-authenticated fixed path. The ordinary
    # override is deliberately limited to explicit source/test mode.
    if getattr(__import__('sys'), 'frozen', False) or os.getenv("GROWTHMAP_PACKAGED_MODE")=="1":
        value=os.getenv("GROWTHMAP_BUNDLED_LICENSE_PUBLIC_KEY")
        return Path(value) if value else bundled
    return Path(os.getenv("GROWTHMAP_LICENSE_PUBLIC_KEY", bundled))
PUBLIC_KEY_PATH = _public_key_path()
EDITIONS = {"personal", "pro", "studio"}
LICENSE_FIELDS = {"schema_version","edition","license_id","major_version","device_allowance","device_binding","issued_at","expires_at","revoked_at","max_active_projects","next_check_in_at","signature"}
LICENSE_REQUIRED = {"schema_version","edition","license_id","major_version","device_allowance","issued_at","max_active_projects","signature"}
ACTIVATION_FIELDS = {"schema_version","certificate_type","product","edition","license_id","activation_id","major_version","device_allowance","device_id","device_public_key","issued_at","expires_at","revoked_at","max_active_projects","next_check_in_at","signature"}
ACTIVATION_DOMAIN=b"growthmap-activation-certificate-v2\0"
DEVICE_ID_RE=re.compile(r"gmdev_[0-9a-f]{64}")
ROLLBACK_TOLERANCE = timedelta(minutes=5)
REVOCATION_FIELDS={"schema_version","assertion_type","product","major_version","license_id","revoked_at","sequence","reason_code","signature"}
REVOCATION_REASONS={None,"refund","chargeback","fraud","terms_violation","administrative"}
REVOCATION_DOMAIN=b"growthmap-revocation-v1\0"
CANONICAL_UTC=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
REVOCATION_FUTURE_SKEW=timedelta(minutes=5)

@dataclass(frozen=True)
class Entitlement:
    state: str = "extraction"
    edition: str = "unpaid"
    license_id: str | None = None
    major_version: int | None = None
    device_allowance: int | None = None
    max_active_projects: int | None = 0
    valid: bool = False
    mutations_allowed: bool = False
    reason: str = "no_trial_state"
    trial_started_at: str | None = None
    trial_expires_at: str | None = None
    trial_days_remaining: int = 0

    def public(self) -> dict[str, Any]: return asdict(self)

def _iso(value: Any, *, canonical: bool=False) -> datetime:
    if not isinstance(value, str) or (canonical and not CANONICAL_UTC.fullmatch(value)): raise ValueError("timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None: raise ValueError("timezone")
    return result.astimezone(timezone.utc)

def strict_json_loads(raw: str) -> dict[str,Any]:
    def pairs(items):
        result={};folded=set()
        for key,value in items:
            fold=key.casefold()
            if key in result: raise ValueError("duplicate_json_key")
            if fold in folded: raise ValueError("case_colliding_json_key")
            result[key]=value;folded.add(fold)
        return result
    return json.loads(raw,object_pairs_hook=pairs)

def stable_file_bytes(path: Path, *, max_bytes: int=65536) -> bytes:
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags)
    try:
        before=os.fstat(fd)
        if not __import__("stat").S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>max_bytes:raise ValueError("unsafe_file")
        chunks=[];remaining=before.st_size
        while remaining:
            part=os.read(fd,min(remaining,65536))
            if not part:raise ValueError("short_read")
            chunks.append(part);remaining-=len(part)
        after=os.fstat(fd)
        if (before.st_dev,before.st_ino,before.st_size,before.st_nlink)!=(after.st_dev,after.st_ino,after.st_size,after.st_nlink):raise ValueError("unstable_file")
        return b"".join(chunks)
    finally:os.close(fd)

def stable_json_file(path: Path, *, max_bytes: int=65536) -> dict[str,Any]:
    return strict_json_loads(stable_file_bytes(path,max_bytes=max_bytes).decode("utf-8"))

def canonical_payload(doc: dict[str, Any]) -> bytes:
    return json.dumps({k:doc[k] for k in sorted(doc) if k != "signature"}, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()

def _device_id(public_key_b64: str) -> str:
    raw=base64.b64decode(public_key_b64,validate=True)
    if len(raw)!=32: raise ValueError("device_public_key")
    Ed25519PublicKey.from_public_bytes(raw)
    return "gmdev_"+__import__("hashlib").sha256(raw).hexdigest()

def verify_document(doc: dict[str, Any], public_key_path: Path=PUBLIC_KEY_PATH, *, now: datetime | None=None, current_major: int=CURRENT_MAJOR_VERSION, device_public_key: str|None=None) -> Entitlement:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        if not isinstance(doc,dict): return Entitlement(reason="invalid_document")
        version=doc.get("schema_version");is_activation=version==2;allowed=ACTIVATION_FIELDS if is_activation else LICENSE_FIELDS;required=ACTIVATION_FIELDS if is_activation else LICENSE_REQUIRED
        invalid_fields=(set(doc)!=allowed) if is_activation else (bool(set(doc)-allowed) or not required<=set(doc))
        if invalid_fields: return Entitlement(reason="invalid_document")
        if isinstance(version,bool) or not isinstance(version,int) or version not in {1,2}: return Entitlement(reason="unsupported_schema")
        if doc["edition"] not in EDITIONS: return Entitlement(reason="invalid_edition")
        if not isinstance(doc["license_id"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",doc["license_id"]): return Entitlement(reason="invalid_license_id")
        for name in ("major_version","device_allowance"):
            if isinstance(doc[name],bool) or not isinstance(doc[name],int) or doc[name]<1: return Entitlement(reason="invalid_"+name)
        # Stable precedence: exact shape/basic primitive types, then signature, then signed semantics.
        raw=public_key_path.read_bytes()
        if b"REPLACE_WITH" in raw: return Entitlement(reason="placeholder_public_key")
        key=serialization.load_pem_public_key(raw)
        if not isinstance(key,Ed25519PublicKey): return Entitlement(reason="invalid_public_key")
        key.verify(base64.b64decode(doc["signature"],validate=True),(ACTIVATION_DOMAIN if is_activation else b"")+canonical_payload(doc))
        if doc["device_allowance"]>2: return Entitlement(reason="invalid_device_allowance")
        if doc["max_active_projects"] is not None: return Entitlement(reason="invalid_limit")
        try: _iso(doc["issued_at"])
        except Exception:return Entitlement(reason="invalid_issued_at")
        try: expiry=_iso(doc["expires_at"]) if doc.get("expires_at") is not None else None
        except Exception:return Entitlement(reason="invalid_expiry")
        try: revoked=_iso(doc["revoked_at"]) if doc.get("revoked_at") is not None else None
        except Exception:return Entitlement(reason="invalid_revocation")
        if is_activation:
            if doc["certificate_type"]!="growthmap_device_activation" or doc["product"]!="growthmap": return Entitlement(reason="invalid_certificate_type")
            if not isinstance(doc["activation_id"],str) or not re.fullmatch(r"gma_[0-9a-f]{32}",doc["activation_id"]): return Entitlement(reason="invalid_activation_id")
            if not isinstance(doc["device_id"],str) or not DEVICE_ID_RE.fullmatch(doc["device_id"]) or _device_id(doc["device_public_key"])!=doc["device_id"]: return Entitlement(reason="invalid_device_binding")
            if not device_public_key: return Entitlement(reason="device_identity_missing",license_id=doc["license_id"],major_version=doc["major_version"])
            if not __import__("hmac").compare_digest(doc["device_public_key"],device_public_key): return Entitlement(reason="wrong_device",license_id=doc["license_id"],major_version=doc["major_version"])
        elif doc.get("device_binding") is not None: return Entitlement(reason="device_binding_unsupported")
        if doc["major_version"]!=current_major: return Entitlement(reason="major_mismatch",major_version=doc["major_version"],license_id=doc["license_id"])
        observed=dict(state="paid_observed",edition=doc["edition"],license_id=doc["license_id"],major_version=doc["major_version"],device_allowance=doc["device_allowance"],max_active_projects=None)
        if expiry is not None and expiry<=now: return Entitlement(**observed,reason="expired")
        if revoked is not None and revoked<=now: return Entitlement(**observed,reason="revoked")
        if "next_check_in_at" not in doc or not is_activation: return Entitlement(state="paid_legacy",edition=doc["edition"],license_id=doc["license_id"],major_version=doc["major_version"],device_allowance=doc["device_allowance"],max_active_projects=None,valid=True,mutations_allowed=False,reason="legacy_bootstrap_required")
        if now>_iso(doc["next_check_in_at"]): return Entitlement(reason="check_in_required",license_id=doc["license_id"],major_version=doc["major_version"])
        return Entitlement(state="paid",edition=doc["edition"],license_id=doc["license_id"],major_version=doc["major_version"],device_allowance=doc["device_allowance"],max_active_projects=None,valid=True,mutations_allowed=True,reason="valid")
    except (OSError,ValueError,TypeError,KeyError,InvalidSignature): return Entitlement(reason="invalid_signature")

def verify_revocation_assertion(doc: dict[str,Any], license_id: str, public_key_path: Path=PUBLIC_KEY_PATH, *, current_major: int=CURRENT_MAJOR_VERSION, minimum_sequence: int=0, now: datetime|None=None, issued_at: str|None=None) -> dict[str,Any]:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not isinstance(doc,dict) or set(doc)!=REVOCATION_FIELDS: raise ValueError("invalid_revocation_document")
    for field in ("schema_version","major_version","sequence"):
        if isinstance(doc[field],bool) or not isinstance(doc[field],int): raise ValueError("invalid_revocation_integer")
    for field in ("assertion_type","product","license_id","revoked_at","signature"):
        if not isinstance(doc[field],str): raise ValueError("invalid_revocation_string")
    if doc["schema_version"]!=1 or doc["assertion_type"]!="growthmap_license_revocation" or doc["product"]!="growthmap": raise ValueError("unsupported_revocation_schema")
    if doc["license_id"]!=license_id: raise ValueError("revocation_license_mismatch")
    if doc["major_version"]!=current_major: raise ValueError("revocation_major_mismatch")
    if doc["sequence"]<=minimum_sequence: raise ValueError("revocation_sequence_replay")
    if doc["reason_code"] not in REVOCATION_REASONS: raise ValueError("invalid_revocation_reason")
    revoked=_iso(doc["revoked_at"],canonical=True)
    if revoked>now+REVOCATION_FUTURE_SKEW: raise ValueError("revocation_from_future")
    if issued_at is not None and revoked<_iso(issued_at): raise ValueError("revocation_before_license_issue")
    raw=public_key_path.read_bytes();key=serialization.load_pem_public_key(raw)
    if not isinstance(key,Ed25519PublicKey): raise ValueError("invalid_public_key")
    key.verify(base64.b64decode(doc["signature"],validate=True),REVOCATION_DOMAIN+canonical_payload(doc))
    return doc

def apply_revocation(value: Entitlement, path: Path=REVOCATION_PATH, *, public_key_path: Path=PUBLIC_KEY_PATH, issued_at: str|None=None) -> Entitlement:
    if value.state not in {"paid","paid_legacy"} or not value.valid or not path.exists(): return value
    try: verify_revocation_assertion(strict_json_loads(path.read_text("utf-8")),value.license_id or "",public_key_path,issued_at=issued_at)
    except Exception: return Entitlement(reason="revocation_state_invalid",license_id=value.license_id,major_version=value.major_version)
    return Entitlement(reason="revoked",license_id=value.license_id,major_version=value.major_version)

def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    parent=path.parent;parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name=="nt":
        # Python dirfd/openat primitives are unavailable on Windows; fail closed on reparse-like parents/files.
        if parent.is_symlink() or (path.exists() and (path.is_symlink() or not path.is_file())):raise ValueError("unsafe_destination")
        fd,name=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle:json.dump(value,handle,separators=(",",":"));handle.flush();os.fsync(handle.fileno())
            os.chmod(name,0o600);os.replace(name,path)
        except Exception:
            try:os.unlink(name)
            except OSError:pass
            raise
        return
    dfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0));name=f".{path.name}.{os.getpid()}.{__import__('secrets').token_hex(8)}.tmp"
    try:
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=dfd)
        try:
            raw=json.dumps(value,separators=(",",":")).encode();os.write(fd,raw);os.fsync(fd)
        finally:os.close(fd)
        os.replace(name,path.name,src_dir_fd=dfd,dst_dir_fd=dfd);os.fsync(dfd)
    except Exception:
        try:os.unlink(name,dir_fd=dfd)
        except OSError:pass
        raise
    finally:os.close(dfd)

def initialize_trial(path: Path=TRIAL_PATH, *, now: datetime | None=None, started_at: str | None=None, installation_id: str="test-installation") -> None:
    """Electron-authorized first-install initialization; never resets existing/corrupt state."""
    if path.exists(): return
    instant=_iso(started_at).isoformat() if started_at else (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,80}",installation_id): raise ValueError("installation_id")
    try: _atomic_json(path,{"schema_version":1,"installation_id":installation_id,"started_at":instant,"last_seen_at":instant})
    except FileExistsError: pass

def trial_entitlement(path: Path=TRIAL_PATH, *, now: datetime | None=None, checkpoint: bool=False) -> Entitlement:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        doc=strict_json_loads(path.read_text("utf-8"))
        if set(doc)!={"schema_version","installation_id","started_at","last_seen_at"} or doc["schema_version"] != 1 or not re.fullmatch(r"[A-Za-z0-9-]{8,80}",doc["installation_id"]): return Entitlement(reason="corrupt_trial_state")
        started,last=_iso(doc["started_at"]),_iso(doc["last_seen_at"])
        if started > now + ROLLBACK_TOLERANCE or now + ROLLBACK_TOLERANCE < last: return Entitlement(reason="clock_rollback",trial_started_at=started.isoformat(),trial_expires_at=(started+timedelta(days=TRIAL_DAYS)).isoformat())
        expires=started+timedelta(days=TRIAL_DAYS)
        if now >= expires: return Entitlement(reason="trial_expired",trial_started_at=started.isoformat(),trial_expires_at=expires.isoformat())
        if checkpoint and now > last: _atomic_json(path,{"schema_version":1,"installation_id":doc["installation_id"],"started_at":started.isoformat(),"last_seen_at":now.isoformat()})
        remaining=max(1,(expires.date()-now.date()).days)
        return Entitlement(state="trial",edition="trial",max_active_projects=TRIAL_ACTIVE_PROJECT_LIMIT,valid=True,mutations_allowed=True,reason="trial_active",trial_started_at=started.isoformat(),trial_expires_at=expires.isoformat(),trial_days_remaining=remaining)
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError): return Entitlement(reason="corrupt_trial_state")

def peek_current_entitlement(*, now: datetime | None=None) -> Entitlement:
    """Cryptographic entitlement lookup with zero file writes."""
    if LICENSE_PATH.exists():
        try: doc=strict_json_loads(LICENSE_PATH.read_text("utf-8")); return apply_revocation(verify_document(doc,public_key_path=_public_key_path(),now=now,device_public_key=os.getenv("GROWTHMAP_DEVICE_PUBLIC_KEY")),public_key_path=_public_key_path(),issued_at=doc.get("issued_at"))
        except (OSError,ValueError): return Entitlement(reason="corrupt_license")
    return trial_entitlement(now=now,checkpoint=False)

def checkpoint_current_entitlement(*, now: datetime | None=None) -> Entitlement:
    value=peek_current_entitlement(now=now)
    if value.state != "trial" or not value.valid or not value.mutations_allowed:
        return value
    return trial_entitlement(now=now,checkpoint=True)

def current_entitlement(*, now: datetime | None=None, checkpoint: bool=False) -> Entitlement:
    return checkpoint_current_entitlement(now=now) if checkpoint else peek_current_entitlement(now=now)
