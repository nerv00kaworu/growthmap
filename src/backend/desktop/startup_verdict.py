"""Authenticate Electron's per-launch startup verdict.

The verdict can only narrow locally verified entitlement. A valid paid license always wins;
no verdict can manufacture paid or trial entitlement.
"""
import hashlib,hmac,os,re
from dataclasses import replace
from desktop.entitlements import Entitlement,peek_current_entitlement

_MODES={"paid","trial","fresh","extraction"}
_NONCE=re.compile(r"[A-Za-z0-9_-]{32,128}")

def verdict_mode() -> str | None:
    mode=os.getenv("GROWTHMAP_STARTUP_VERDICT_MODE","")
    nonce=os.getenv("GROWTHMAP_STARTUP_VERDICT_NONCE","")
    supplied=os.getenv("GROWTHMAP_STARTUP_VERDICT_MAC","")
    token=os.getenv("GROWTHMAP_SESSION_TOKEN","")
    if mode not in _MODES or not _NONCE.fullmatch(nonce) or not token or not re.fullmatch(r"[0-9a-f]{64}",supplied):return None
    expected=hmac.new(token.encode(),f"growthmap-startup-v1:{mode}:{nonce}".encode(),hashlib.sha256).hexdigest()
    return mode if hmac.compare_digest(supplied,expected) else None

def effective_entitlement() -> Entitlement:
    base=peek_current_entitlement()
    if base.state=="paid" and base.valid and base.mutations_allowed:return base
    mode=verdict_mode()
    # Compatibility for authenticated first-install initialization: it cannot revive an
    # existing trial because initialize_trial never overwrites state.
    if mode is None and os.getenv("GROWTHMAP_FRESH_INSTALL")=="1":return base
    if mode=="trial" and base.state=="trial" and base.valid and base.mutations_allowed:return base
    if mode=="fresh" and os.getenv("GROWTHMAP_FRESH_INSTALL")=="1" and base.reason in {"no_trial_state","corrupt_trial_state"}:
        return Entitlement(state="trial",edition="trial",max_active_projects=2,valid=True,mutations_allowed=True,reason="authenticated_fresh_install")
    return Entitlement(reason="electron_forced_extraction" if mode=="extraction" else "startup_verdict_invalid")
