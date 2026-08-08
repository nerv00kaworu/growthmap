"""Dependency-injected Gift License candidate HTTP boundary; never a production composition root."""
from __future__ import annotations
import hmac,ipaddress,json,re,threading,time
from collections import OrderedDict,deque
from typing import Protocol,runtime_checkable
from urllib.parse import urlsplit
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,StrictInt,StrictStr,ValidationError
from .gift_service import GiftLicenseService

MAX_TOKEN=4096
MAX_SECURITY_HEADER=4096
MAX_HEADER_COUNT=64
MAX_HEADER_BYTES=16384
TOKEN_RE=re.compile(r"[A-Za-z0-9._~-]{1,4096}")
DNS_RE=re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

@runtime_checkable
class AdminSessionVerifier(Protocol):
 def verify(self,token:str)->bool:...
class CreateBody(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 edition:StrictStr="personal";major_version:StrictInt=1;seat_limit:StrictInt=2;expires_at:None=None;check_in_days:StrictInt=30
class ClaimBody(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 claim_key:StrictStr;device_public_key:StrictStr
class CompleteBody(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 challenge_id:StrictStr;proof:StrictStr
class DeviceBody(BaseModel):
 model_config=ConfigDict(extra="forbid",strict=True)
 device_id:StrictStr

def canonical_https_origin(value):
 if type(value) is not str or len(value)>512:return None
 try:url=urlsplit(value)
 except ValueError:return None
 if url.scheme!="https" or not url.hostname or url.username is not None or url.password is not None or url.path or url.query or url.fragment:return None
 host=url.hostname
 try:
  ipaddress.ip_address(host);return None
 except ValueError:pass
 if host!=host.lower() or host.endswith(".") or not DNS_RE.fullmatch(host) or "_" in host:return None
 try:port=url.port
 except ValueError:return None
 if port is not None and (port==443 or not 1<=port<=65535):return None
 canonical="https://"+host+(f":{port}" if port is not None else "")
 return canonical if value==canonical else None

def peer_identity(request):
 return request.client.host if request.client and request.client.host else "unknown"

class Limiter:
 def __init__(self,limit,*,capacity=1024,window=60.0,clock=time.monotonic):
  if type(limit) is not int or limit<1 or type(capacity) is not int or capacity<1:raise ValueError("invalid limiter")
  self.limit,self.capacity,self.window,self.clock=limit,capacity,window,clock;self.rows=OrderedDict();self.lock=threading.Lock()
 def check(self,bucket,key):
  now=self.clock();identity=(str(bucket),str(key))
  with self.lock:
   for prior in list(self.rows):
    q=self.rows[prior]
    while q and q[0]<=now-self.window:q.popleft()
    if not q:del self.rows[prior]
   q=self.rows.get(identity)
   if q is None:
    while len(self.rows)>=self.capacity:self.rows.popitem(last=False)
    q=deque();self.rows[identity]=q
   else:self.rows.move_to_end(identity)
   if len(q)>=self.limit:raise HTTPException(429,"rate limit")
   q.append(now)

async def body(request,model):
 raw=await request.body()
 if not raw or len(raw)>8192:raise HTTPException(400,"invalid request")
 def pairs(items):
  out={};seen=set()
  for key,value in items:
   if type(key) is not str or key.casefold() in seen:raise ValueError
   seen.add(key.casefold());out[key]=value
  return out
 try:return model.model_validate(json.loads(raw,object_pairs_hook=pairs))
 except (ValueError,ValidationError,json.JSONDecodeError):raise HTTPException(400,"invalid request") from None

def raw_headers(request):
 values={b"authorization":[],b"origin":[],b"x-csrf-token":[]};headers=request.scope.get("headers") or []
 if len(headers)>MAX_HEADER_COUNT or sum(len(name)+len(value) for name,value in headers)>MAX_HEADER_BYTES:raise HTTPException(400,"invalid request")
 for name,value in headers:
  lowered=name.lower()
  if lowered in values:
   if len(name)>64 or len(value)>MAX_SECURITY_HEADER:raise HTTPException(403,"admin authentication failed")
   values[lowered].append(value)
 return values

def create_candidate_app(*,authority,session_verifier:AdminSessionVerifier,allowed_admin_origin:str,csrf_secret:str,rate_limit:int=30,limiter_capacity:int=1024,client_identity_resolver=peer_identity):
 origin=canonical_https_origin(allowed_admin_origin)
 if authority is None or not isinstance(session_verifier,AdminSessionVerifier) or origin is None or type(csrf_secret) is not str or not csrf_secret or len(csrf_secret.encode())>MAX_SECURITY_HEADER or type(rate_limit) is not int or rate_limit<1 or type(limiter_capacity) is not int or limiter_capacity<1 or not callable(client_identity_resolver):raise RuntimeError("gift candidate dependencies unavailable")
 service=GiftLicenseService(authority);app=FastAPI(title="GrowthMap Gift Candidate");limiter=Limiter(rate_limit,capacity=limiter_capacity)
 @app.middleware("http")
 async def headers(request,call_next):
  try:
   raw_headers(request)
   response=await call_next(request)
  except HTTPException as error:response=JSONResponse({"detail":error.detail},error.status_code)
  except Exception:response=JSONResponse({"detail":"Internal server error"},500)
  response.headers["Cache-Control"]="no-store";response.headers["Pragma"]="no-cache";response.headers["Referrer-Policy"]="no-referrer";return response
 def identity(request):
  try:value=client_identity_resolver(request)
  except Exception:raise HTTPException(403,"admin authentication failed") from None
  if type(value) is not str or not value or len(value)>256:raise HTTPException(403,"admin authentication failed")
  return value
 def admin(request):
  limiter.check("admin",identity(request));values=raw_headers(request)
  if any(len(values[name])!=1 for name in values):raise HTTPException(403,"admin authentication failed")
  authorization,raw_origin,csrf=(values[b"authorization"][0],values[b"origin"][0],values[b"x-csrf-token"][0])
  if b"," in authorization or b"\r" in authorization or b"\n" in authorization:raise HTTPException(403,"admin authentication failed")
  try:supplied=authorization.decode("ascii");request_origin=raw_origin.decode("ascii");request_csrf=csrf.decode("utf-8","strict")
  except UnicodeError:raise HTTPException(403,"admin authentication failed") from None
  match=re.fullmatch(r"Bearer ([A-Za-z0-9._~-]{1,4096})",supplied)
  token=match.group(1) if match else ""
  try:ok=bool(match) and session_verifier.verify(token) is True
  except Exception:ok=False
  if not(ok and hmac.compare_digest(request_origin,origin) and hmac.compare_digest(request_csrf,csrf_secret)):raise HTTPException(403,"admin authentication failed")
 def unavailable():return HTTPException(404,"gift unavailable")
 @app.post("/v1/gifts/claim/challenge")
 async def challenge(request:Request):
  limiter.check("claim",identity(request));value=await body(request,ClaimBody)
  try:return {"state":"challenge_issued","challenge":service.challenge(value.claim_key,value.device_public_key)}
  except Exception:raise unavailable() from None
 @app.post("/v1/gifts/claim/complete")
 async def complete(request:Request):
  limiter.check("claim",identity(request));value=await body(request,CompleteBody)
  try:return {"state":"activated","certificate":service.complete(value.challenge_id,value.proof)}
  except Exception:raise unavailable() from None
 @app.post("/v1/admin/gifts")
 async def create(request:Request):
  admin(request);value=await body(request,CreateBody)
  if value.major_version != 1:raise HTTPException(422,"invalid gift policy")
  try:return JSONResponse(service.create(**value.model_dump()),201)
  except ValueError:raise HTTPException(422,"invalid gift policy") from None
 @app.get("/v1/admin/gifts")
 async def listing(request:Request):admin(request);return service.list()
 @app.get("/v1/admin/gifts/{gift_id}")
 async def get(gift_id:str,request:Request):
  admin(request)
  try:return service.get(gift_id)
  except ValueError:raise unavailable() from None
 @app.post("/v1/admin/gifts/{gift_id}/recover")
 async def recover(gift_id:str,request:Request):
  admin(request)
  try:return service.rotate(gift_id)
  except ValueError:raise unavailable() from None
 @app.post("/v1/admin/gifts/{gift_id}/revoke")
 async def revoke(gift_id:str,request:Request):
  admin(request)
  try:return service.revoke(gift_id)
  except ValueError:raise unavailable() from None
 @app.get("/v1/admin/gifts/{gift_id}/devices")
 async def devices(gift_id:str,request:Request):
  admin(request)
  try:return service.devices(gift_id)
  except ValueError:raise unavailable() from None
 @app.post("/v1/admin/gifts/{gift_id}/devices/deactivate")
 async def deactivate(gift_id:str,request:Request):
  admin(request);value=await body(request,DeviceBody)
  try:return {"deactivated":service.deactivate(gift_id,value.device_id)}
  except ValueError:raise unavailable() from None
 app.state.gift_limiter=limiter
 return app

def from_env(*_args,**_kwargs):raise RuntimeError("production Gift composition blocked: reviewed external dependencies unavailable")
