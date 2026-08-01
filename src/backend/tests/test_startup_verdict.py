import base64,hashlib,hmac,os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def signed_env(mode='paid',token='verdict-test-token',nonce='N'*43,session='S'*43):
 from desktop.startup_verdict import canonical_startup_proof,canonical_startup_verdict
 key=Ed25519PrivateKey.generate();pub=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();proof=base64.b64encode(key.sign(canonical_startup_proof(mode,pub,nonce,session))).decode();mac=hmac.new(token.encode(),canonical_startup_verdict(mode,pub,nonce,session,proof),hashlib.sha256).hexdigest()
 return {'GROWTHMAP_SESSION_TOKEN':token,'GROWTHMAP_STARTUP_VERDICT_MODE':mode,'GROWTHMAP_DEVICE_PUBLIC_KEY':pub,'GROWTHMAP_STARTUP_VERDICT_NONCE':nonce,'GROWTHMAP_STARTUP_SESSION':session,'GROWTHMAP_STARTUP_DEVICE_PROOF':proof,'GROWTHMAP_STARTUP_VERDICT_MAC':mac}
def apply(monkeypatch,env):
 for k,v in env.items():monkeypatch.setenv(k,v)
def test_bound_private_key_verdict_validates(monkeypatch):
 from desktop.startup_verdict import verdict_validation
 apply(monkeypatch,signed_env());assert verdict_validation()==('paid','valid')
def test_replay_proof_fails_for_new_session(monkeypatch):
 from desktop.startup_verdict import verdict_validation
 env=signed_env();env['GROWTHMAP_STARTUP_SESSION']='T'*43;apply(monkeypatch,env);assert verdict_validation()==(None,'device_proof_invalid')
def test_attacker_copied_cert_and_public_env_without_private_proof_is_extraction(monkeypatch):
 import desktop.startup_verdict as verdict
 from desktop.entitlements import Entitlement
 monkeypatch.setattr(verdict,'peek_current_entitlement',lambda:Entitlement(state='paid',edition='personal',valid=True,mutations_allowed=True,reason='valid'))
 env=signed_env();env['GROWTHMAP_STARTUP_DEVICE_PROOF']=base64.b64encode(b'x'*64).decode();apply(monkeypatch,env);assert verdict.effective_entitlement().state=='extraction'
def test_paid_requires_paid_policy_after_valid_proof(monkeypatch):
 import desktop.startup_verdict as verdict
 from desktop.entitlements import Entitlement
 monkeypatch.setattr(verdict,'peek_current_entitlement',lambda:Entitlement(state='paid',edition='personal',valid=True,mutations_allowed=True,reason='valid'))
 apply(monkeypatch,signed_env('paid'));assert verdict.effective_entitlement().state=='paid'
 apply(monkeypatch,signed_env('extraction'));assert verdict.effective_entitlement().state=='extraction'
def test_ci_diagnostic_never_leaks_secrets(monkeypatch,capsys):
 monkeypatch.setenv('CI','true');monkeypatch.setenv('GROWTHMAP_SESSION_TOKEN','never-print-this-token');monkeypatch.setenv('GROWTHMAP_STARTUP_VERDICT_MAC','0'*64)
 from desktop.startup_verdict import _invalid_reason
 result=_invalid_reason('mac_mismatch')+capsys.readouterr().err;assert 'mac_mismatch' in result and 'never-print' not in result and '0'*64 not in result
