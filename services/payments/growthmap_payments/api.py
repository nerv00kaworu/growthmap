"""Candidate HTTP boundary; production auth and official facilitator remain fail-closed."""
from __future__ import annotations
import base64,hashlib,hmac,json,logging,os,threading,time
from collections import defaultdict,deque
from pathlib import Path
from fastapi import FastAPI,Header,HTTPException,Request
from pydantic import BaseModel,ConfigDict,StrictStr,ValidationError
from fastapi.responses import JSONResponse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .service import Config,PaymentService
from .facilitator import OfficialX402Facilitator
from .public_config import APPROVED_BASE_RECIPIENT
class MockFacilitator:
 """Nested authorization envelope for isolated tests; not an official SDK implementation."""
 def __init__(self):self.settled={};self.fail=False
 def verify(self,signature,requirements):
  try:env=json.loads(base64.urlsafe_b64decode(signature+'='*(-len(signature)%4)));auth=env["payload"]["authorization"]
  except Exception as e:raise ValueError("malformed PAYMENT-SIGNATURE envelope") from e
  if set(env)!={"x402Version","scheme","network","payload"} or env["x402Version"]!=2 or env["scheme"]!="exact":raise ValueError("wrong envelope")
  req=requirements["accepts"][0]
  checks={"network":env["network"],"asset":auth.get("asset"),"amount":auth.get("value"),"payTo":auth.get("to"),"orderId":auth.get("orderId")}
  expected={"network":req["network"],"asset":req["asset"],"amount":req["amount"],"payTo":req["payTo"],"orderId":req["extra"]["orderId"]}
  if checks!=expected or not re_address(auth.get("from")) or not auth.get("nonce") or not isinstance(auth.get("validBefore"),int) or auth["validBefore"]<int(time.time()):raise ValueError("authorization binding")
  return {"amount":auth["value"],"nonce":auth["nonce"],"proof_id":hashlib.sha256(signature.encode()).hexdigest(),"payer":auth["from"]}
 def settle(self,signature,requirements):
  value=self.verify(signature,requirements)
  if self.fail:raise RuntimeError("mock settlement ambiguity")
  result=self.settled.get(value["nonce"]) or {"success":True,"transaction":"mock:"+hashlib.sha256(signature.encode()).hexdigest(),"payer":"0x"+"2"*40,"finality_at":PaymentService.now(),"finality_basis":"isolated_test_fixture"};self.settled[value["nonce"]]=result;return result
def re_address(v):
 import re
 return isinstance(v,str) and re.fullmatch(r"0x[0-9a-fA-F]{40}",v) is not None
class Limiter:
 def __init__(self,limit):self.limit=limit;self.rows=defaultdict(deque);self.lock=threading.Lock()
 def check(self,bucket,key,consume=True):
  now=time.monotonic()
  with self.lock:
   q=self.rows[(bucket,key)]
   while q and q[0]<now-60:q.popleft()
   if len(q)>=self.limit:raise HTTPException(429,"rate limit")
   if consume:q.append(now)
def load_key(path):
 if not path:return None
 key=serialization.load_pem_private_key(Path(path).read_bytes(),password=None)
 if not isinstance(key,Ed25519PrivateKey):raise RuntimeError("Ed25519 key required")
 return key
def load_settlement_mac_key(path):
 """Load an external binary trust root; never accept the secret directly in env."""
 if not path:return None
 p=Path(path);raw=p.read_bytes()
 if len(raw)<32:raise RuntimeError("external settlement MAC key file is weak")
 return raw
class ActivationChallengeBody(BaseModel):
 model_config=ConfigDict(extra='forbid',strict=True)
 order_id:StrictStr;recovery_code:StrictStr;device_public_key:StrictStr
class ActivationCompleteBody(BaseModel):
 model_config=ConfigDict(extra='forbid',strict=True)
 challenge_id:StrictStr;proof:StrictStr
async def strict_body(request,model):
 raw=await request.body()
 if not raw or len(raw)>8192:raise ValueError('invalid body')
 seen=[]
 def pairs(items):
  folded=set();result={}
  for key,value in items:
   if not isinstance(key,str) or key.casefold() in folded:raise ValueError('duplicate field')
   folded.add(key.casefold());result[key]=value
  return result
 try:return model.model_validate(json.loads(raw,object_pairs_hook=pairs))
 except (ValueError,ValidationError,json.JSONDecodeError) as error:raise ValueError('invalid body') from error
def create_app(config:Config,facilitator=None,reconciler=None,authority=None):
 if config.production:
  if isinstance(facilitator,MockFacilitator):raise RuntimeError("mock facilitator forbidden in production")
  # No source-level constructor, marker, subclass, provider, or client proves
  # production authorization. The reviewed composition root is not integrated.
  raise RuntimeError("production service blocked: reviewed Argon2id session provider not integrated")
 service=PaymentService(config,facilitator);app=FastAPI(title="GrowthMap Payments Candidate",version="1.0-device-activation");limiter=Limiter(config.rate_limit)
 @app.middleware("http")
 async def prevent_sensitive_response_caching(request:Request,call_next):
  try:response=await call_next(request)
  except Exception:
   logging.getLogger("growthmap_payments.api").exception("Unhandled payment API error",extra={"path":request.url.path})
   response=JSONResponse(status_code=500,content={"detail":"Internal server error"})
  response.headers["Cache-Control"]="no-store"
  response.headers["Pragma"]="no-cache"
  response.headers["Referrer-Policy"]="no-referrer"
  return response
 def admin(request,authorization,csrf):
  ip=request.client.host if request.client else "unknown"
  # The bounded digest is non-secret and prevents one bad token from consuming
  # every per-IP slot; the coarse IP bucket prevents rotating-token bypass.
  auth_bytes=(authorization or "").encode()[:4096]
  fingerprint=hashlib.sha256(auth_bytes).hexdigest()[:24]
  # A saturated failed-auth bucket blocks only unauthenticated attempts; a
  # bounded local SHA-256 precheck lets known-good sessions bypass NAT abuse.
  token=authorization.removeprefix("Bearer ") if authorization else ""
  supplied_hash=hashlib.sha256(token.encode()).hexdigest();token_ok=bool(config.admin_secret_hash) and hmac.compare_digest(supplied_hash,config.admin_secret_hash)
  if not token_ok:limiter.check("admin-ip-failed",ip,consume=False)
  # Consume failed-auth buckets only after the bounded precheck fails. A future
  # expensive provider must remain behind this rotating-token/IP gate.
  if not token_ok:
   limiter.check("admin-auth",f"{ip}:{fingerprint}");limiter.check("admin-ip-failed",ip);raise HTTPException(403,"admin authentication failed")
  origin_ok=hmac.compare_digest(request.headers.get("origin","").encode(),config.allowed_admin_origin.encode())
  csrf_ok=bool(config.csrf_secret) and hmac.compare_digest((csrf or "").encode(),config.csrf_secret.encode())
  if not (origin_ok and csrf_ok):
   limiter.check("admin-ip-failed",ip);raise HTTPException(403,"admin authentication failed")
  limiter.check("admin-action",ip)
 @app.post('/v1/orders')
 async def create(body:dict,request:Request):
  limiter.check("orders",request.client.host if request.client else "unknown")
  try:return service.create_order(body.get('rail',''),body.get('email',''),body.get('license_name','Personal'))
  except ValueError as e:raise HTTPException(422,str(e))
 @app.post('/v1/orders/{oid}/purchase')
 async def purchase(oid,payment_signature:str|None=Header(None,alias='PAYMENT-SIGNATURE')):
  try:challenge=service.challenge(oid)
  except (KeyError,ValueError) as e:raise HTTPException(410,str(e))
  if not payment_signature:return JSONResponse(status_code=402,content={"error":"payment_required","resource":challenge["resource"]},headers={"PAYMENT-REQUIRED":base64.b64encode(json.dumps(challenge,separators=(',',':')).encode()).decode(),"Cache-Control":"no-store"})
  if facilitator is None:raise HTTPException(503,"official facilitator integration blocked")
  try:verified=facilitator.verify(payment_signature,challenge);intent=service.prepare_x402_intent(oid,verified["proof_id"],verified["nonce"],int(verified["amount"]),verified.get("payer"))
  except ValueError as e:raise HTTPException(409,str(e))
  try:
   settled=facilitator.settle(payment_signature,challenge)
   if not settled.get("success"):raise RuntimeError("ambiguous")
   evidence=settled.get("evidence",settled);service.record_settlement_result(intent["intent_id"],settled["transaction"],hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest(),settled.get("source","isolated-test-facilitator"),settled.get("finality_at"),payer=settled.get("payer"),finality_basis=settled.get("finality_basis"));service.finalize_x402_intent(intent["intent_id"])
  except Exception as e:
   service.mark_intent_ambiguous(intent["intent_id"],str(e));raise HTTPException(409,"settlement ambiguous; manual reconciliation required; never automatically retried") from e
  if authority is None:return JSONResponse({"order_id":oid,"state":"payment_settled_activation_pending"},status_code=202)
  try:service.deliver_entitlement(oid,authority)
  except Exception:return JSONResponse({"order_id":oid,"state":"payment_settled_activation_pending"},status_code=202)
  return {"order_id":oid,"state":"activation_required","transaction":settled["transaction"]}
 @app.post('/v1/orders/{oid}/paypal-submit')
 async def paypal_submit(oid,body:dict,request:Request):
  limiter.check("orders",request.client.host if request.client else "unknown")
  try:service.paypal_submit(oid,str(body.get('transaction_id','')));return {"state":"pending_payment","notice":"Manual dashboard verification required; screenshots are not evidence."}
  except ValueError as e:raise HTTPException(409,str(e))
 @app.get('/v1/admin/orders')
 async def list_orders(request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
  admin(request,authorization,csrf)
  return JSONResponse(service.admin_list_orders(),headers={"Cache-Control":"no-store"})
 @app.post('/v1/admin/orders/{oid}/paypal-confirm')
 async def paypal_confirm(oid,body:dict,request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
  admin(request,authorization,csrf)
  try:return service.paypal_confirm(oid,body['transaction_id'],body['attestation'])
  except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
 @app.post('/v1/admin/intents/{intent_id}/reconcile')
 async def reconcile(intent_id,request:Request,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
  admin(request,authorization,csrf)
  if reconciler is None:raise HTTPException(503,"official reconciliation adapter blocked")
  try:return service.reconcile_intent(intent_id,reconciler,"admin-session")
  except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
 @app.post('/v1/admin/orders/{oid}/{action}')
 async def action(oid,action,request:Request,body:dict|None=None,authorization:str|None=Header(None),csrf:str|None=Header(None,alias='X-CSRF-Token')):
  admin(request,authorization,csrf)
  try:return service.admin_transition(oid,action,(body or {}).get("reason_code"))
  except KeyError as e:raise HTTPException(404,str(e))
  except ValueError as e:raise HTTPException(409,str(e))
 def unavailable():return JSONResponse({"state":"not_found_or_unavailable"},status_code=404)
 @app.post('/v1/activation/challenge')
 async def activation_challenge_endpoint(request:Request):
  limiter.check("activation",request.client.host if request.client else "unknown")
  if authority is None:return unavailable()
  try:body=await strict_body(request,ActivationChallengeBody)
  except ValueError:return unavailable()
  row=service.authenticated_entitlement(body.order_id,body.recovery_code)
  if not row:return unavailable()
  try:challenge=authority.issue_activation_challenge(license_id=row["license_id"],device_public_key=body.device_public_key)
  except (ValueError,TypeError):return unavailable()
  return {"state":"challenge_issued","challenge":challenge}
 @app.post('/v1/activation/complete')
 async def activation_complete_endpoint(request:Request):
  limiter.check("activation",request.client.host if request.client else "unknown")
  if authority is None:return unavailable()
  try:body=await strict_body(request,ActivationCompleteBody);certificate=authority.activate_challenge(challenge_id=body.challenge_id,proof=body.proof)
  except (ValueError,TypeError):return unavailable()
  return {"state":"activated","certificate":certificate}
 app.state.payments=service;return app
def from_env():
 environment=os.getenv('GROWTHMAP_PAYMENTS_ENV','test')
 if environment not in {'production','development','test'}:raise RuntimeError('invalid payments environment')
 production=environment=='production';test_mode=os.getenv('GROWTHMAP_PAYMENTS_TEST_MODE')=='1'
 raw_live=os.getenv('GROWTHMAP_ALLOW_LIVE_PAYMENT_RECIPIENT')
 if raw_live not in {None,'0','1'}:raise RuntimeError('invalid live payment recipient opt-in')
 allow_live=raw_live=='1'
 if production and test_mode:raise RuntimeError("test facilitator forbidden in production")
 recipient=os.getenv('GROWTHMAP_X402_RECIPIENT','')
 if production and recipient!=APPROVED_BASE_RECIPIENT:raise RuntimeError("production payment recipient missing or not approved")
 if not production and recipient.lower()==APPROVED_BASE_RECIPIENT and not allow_live:raise RuntimeError('approved live payment recipient forbidden outside production')
 config=Config(Path(os.getenv('GROWTHMAP_PAYMENTS_DB','payments.sqlite3')),recipient,os.getenv('GROWTHMAP_ADMIN_SESSION_SHA256',''),load_key(os.getenv('GROWTHMAP_SIGNING_KEY_FILE')),os.getenv('GROWTHMAP_ADMIN_ORIGIN',''),os.getenv('GROWTHMAP_CSRF_SECRET',''),os.getenv('GROWTHMAP_PURCHASE_RESOURCE_BASE',''),production=production,isolated_test=test_mode,settlement_mac_key=load_settlement_mac_key(os.getenv('GROWTHMAP_SETTLEMENT_MAC_KEY_FILE')),settlement_checkpoint_path=Path(os.environ['GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE']) if os.getenv('GROWTHMAP_SETTLEMENT_CHECKPOINT_FILE') else None,environment=environment,allow_live_payment_recipient=allow_live)
 return create_app(config,MockFacilitator() if test_mode else None)
