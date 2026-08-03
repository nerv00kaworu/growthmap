"""Authenticate Electron's per-launch policy and device possession proof."""
import base64,hashlib,hmac,json,os,re,sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from desktop.entitlements import Entitlement,peek_current_entitlement
_MODES={"paid","trial","fresh","extraction"};_NONCE=re.compile(r"[A-Za-z0-9_-]{32,128}");_MAC=re.compile(r"[0-9a-f]{64}")
_PREFIX="growthmap-startup-v2";_PROOF_DOMAIN=b"growthmap-device-startup-v1\0"
def _fields(mode,device,nonce,session):return {"device_public_key":device,"mode":mode,"nonce":nonce,"session":session}
def canonical_startup_proof(mode,device,nonce,session):return _PROOF_DOMAIN+json.dumps(_fields(mode,device,nonce,session),sort_keys=True,separators=(",",":")).encode()
def canonical_startup_verdict(mode,device,nonce,session,proof):return f"{_PREFIX}:{mode}:{device}:{nonce}:{session}:{proof}".encode()
def _fingerprint(value):return hashlib.sha256(value.encode()).hexdigest()[:12]
def verdict_validation():
 mode=os.getenv("GROWTHMAP_STARTUP_VERDICT_MODE","");device=os.getenv("GROWTHMAP_DEVICE_PUBLIC_KEY","");nonce=os.getenv("GROWTHMAP_STARTUP_VERDICT_NONCE","");session=os.getenv("GROWTHMAP_STARTUP_SESSION","");proof=os.getenv("GROWTHMAP_STARTUP_DEVICE_PROOF","");supplied=os.getenv("GROWTHMAP_STARTUP_VERDICT_MAC","");token=os.getenv("GROWTHMAP_SESSION_TOKEN","")
 if mode not in _MODES:return None,"missing_or_bad_mode"
 if not _NONCE.fullmatch(nonce):return None,"bad_nonce_or_session"
 if not token or not _MAC.fullmatch(supplied):return None,"missing_or_bad_mac"
 # Backward-compatible trial/fresh/extraction policy transport. It can never authorize paid.
 if mode!="paid" and not session and not proof and not device:
  legacy=hmac.new(token.encode(),f"growthmap-startup-v1:{mode}:{nonce}".encode(),hashlib.sha256).hexdigest()
  return (mode,"valid_legacy_policy") if hmac.compare_digest(supplied,legacy) else (None,"mac_mismatch")
 if not _NONCE.fullmatch(session):return None,"bad_nonce_or_session"
 try:
  raw=base64.b64decode(device,validate=True);signature=base64.b64decode(proof,validate=True)
  if len(raw)!=32:raise ValueError()
  Ed25519PublicKey.from_public_bytes(raw).verify(signature,canonical_startup_proof(mode,device,nonce,session))
 except Exception:return None,"device_proof_invalid"
 expected=hmac.new(token.encode(),canonical_startup_verdict(mode,device,nonce,session,proof),hashlib.sha256).hexdigest()
 return (mode,"valid") if hmac.compare_digest(supplied,expected) else (None,"mac_mismatch")
def verdict_mode():return verdict_validation()[0]
def _invalid_reason(category):
 if os.getenv("CI")!="true":return "startup_verdict_invalid"
 token=os.getenv("GROWTHMAP_SESSION_TOKEN","");mac=os.getenv("GROWTHMAP_STARTUP_VERDICT_MAC","");detail=f"startup_verdict_invalid:{category}:token_fp={_fingerprint(token)}:mac_fp={_fingerprint(mac)}";print("[startup-verdict] "+detail,file=sys.stderr,flush=True);return detail
def effective_entitlement():
 mode,category=verdict_validation()
 if mode is None:return Entitlement(reason=_invalid_reason(category))
 base=peek_current_entitlement()
 # Paid is accepted only after the launch MAC and private-key possession proof validate.
 if mode=="paid" and base.state=="paid" and base.valid and base.mutations_allowed:return base
 if base.state=="paid_legacy" and base.valid and not base.mutations_allowed:return base
 if mode in {"trial","fresh"} and base.state=="trial" and base.valid and base.mutations_allowed:return base
 if mode=="fresh" and os.getenv("GROWTHMAP_FRESH_INSTALL")=="1" and base.reason=="no_trial_state":return Entitlement(state="trial",edition="trial",max_active_projects=2,valid=True,mutations_allowed=True,reason="authenticated_fresh_install")
 return Entitlement(reason="electron_forced_extraction" if mode=="extraction" else "startup_policy_mismatch")
