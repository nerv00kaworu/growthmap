"""Authenticate Electron's per-launch startup verdict.

The verdict can only narrow locally verified entitlement. A valid paid license always wins;
no verdict can manufacture paid or trial entitlement.
"""
import hashlib,hmac,os,re,sys
from dataclasses import replace
from desktop.entitlements import Entitlement,peek_current_entitlement

_MODES={"paid","trial","fresh","extraction"}
_NONCE=re.compile(r"[A-Za-z0-9_-]{32,128}")
_MAC=re.compile(r"[0-9a-f]{64}")
_PREFIX="growthmap-startup-v1"

def canonical_startup_verdict(mode: str, nonce: str) -> bytes:
    return f"{_PREFIX}:{mode}:{nonce}".encode("utf-8")

def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

def verdict_validation() -> tuple[str | None,str]:
    mode=os.getenv("GROWTHMAP_STARTUP_VERDICT_MODE","")
    nonce=os.getenv("GROWTHMAP_STARTUP_VERDICT_NONCE","")
    supplied=os.getenv("GROWTHMAP_STARTUP_VERDICT_MAC","")
    token=os.getenv("GROWTHMAP_SESSION_TOKEN","")
    if not mode:return None,"missing_mode"
    if mode not in _MODES:return None,"bad_mode"
    if not nonce:return None,"missing_nonce"
    if not _NONCE.fullmatch(nonce):return None,"bad_nonce"
    if not token:return None,"missing_token"
    if not supplied:return None,"missing_mac"
    if not _MAC.fullmatch(supplied):return None,"bad_mac_format"
    expected=hmac.new(token.encode("utf-8"),canonical_startup_verdict(mode,nonce),hashlib.sha256).hexdigest()
    return (mode,"valid") if hmac.compare_digest(supplied,expected) else (None,"mac_mismatch")

def verdict_mode() -> str | None:
    return verdict_validation()[0]

def _invalid_reason(category: str) -> str:
    if os.getenv("CI") != "true":return "startup_verdict_invalid"
    # CI-only safe telemetry: lengths and one-way fingerprints, never token/MAC values.
    mode=os.getenv("GROWTHMAP_STARTUP_VERDICT_MODE","");nonce=os.getenv("GROWTHMAP_STARTUP_VERDICT_NONCE","")
    mac=os.getenv("GROWTHMAP_STARTUP_VERDICT_MAC","");token=os.getenv("GROWTHMAP_SESSION_TOKEN","")
    detail=f"startup_verdict_invalid:{category}:mode={mode or '-'}:nonce_len={len(nonce)}:token_len={len(token)}:mac_len={len(mac)}:token_fp={_fingerprint(token)}:mac_fp={_fingerprint(mac)}"
    print(f"[startup-verdict] {detail}",file=sys.stderr,flush=True)
    return detail

def effective_entitlement() -> Entitlement:
    base=peek_current_entitlement()
    if base.state=="paid" and base.valid and base.mutations_allowed:return base
    mode,category=verdict_validation()
    if mode in {"trial","fresh"} and base.state=="trial" and base.valid and base.mutations_allowed:return base
    if mode=="fresh" and os.getenv("GROWTHMAP_FRESH_INSTALL")=="1" and base.reason=="no_trial_state":
        return Entitlement(state="trial",edition="trial",max_active_projects=2,valid=True,mutations_allowed=True,reason="authenticated_fresh_install")
    return Entitlement(reason="electron_forced_extraction" if mode=="extraction" else _invalid_reason(category))
