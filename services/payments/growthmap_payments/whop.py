"""Bounded, provider-neutral Whop webhook verification seam.

This module deliberately does not implement or guess Whop signature semantics.  A
reviewed adapter must authenticate the bounded request and return authenticated
payload bytes; only then is the strict internal event parsed.
"""
from __future__ import annotations

import json,re
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Iterable,Mapping,Protocol

MAX_BODY_BYTES=64*1024
MAX_SIGNATURE_HEADERS=8
MAX_HEADER_NAME_BYTES=128
MAX_HEADER_VALUE_BYTES=4096
MAX_VERIFIED_BODY_BYTES=64*1024
_SIGNATURE_HEADER=re.compile(r"(?:signature|webhook|whop)",re.I)
_TOKEN=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_KINDS={"paid","refund","dispute","chargeback"}

class WhopVerifier(Protocol):
 def verify(self,raw_body:bytes,signature_headers:Mapping[str,str])->bytes: ...

@dataclass(frozen=True)
class VerifiedWhopEvent:
 event_id:str
 kind:str
 occurred_at:str
 order_id:str
 provider_order_ref:str
 provider_payment_ref:str

class WhopIngressError(ValueError):pass

def bounded_signature_headers(raw_headers:Iterable[tuple[bytes,bytes]])->dict[str,str]:
 """Select and decode signature-related ASGI headers after byte-level caps."""
 selected=[]
 for raw_name,raw_value in raw_headers:
  if type(raw_name) is not bytes or type(raw_value) is not bytes or not raw_name or len(raw_name)>MAX_HEADER_NAME_BYTES:raise WhopIngressError("invalid webhook")
  lower=raw_name.lower()
  if any(token in lower for token in (b"signature",b"webhook",b"whop")):
   if not raw_value or len(raw_value)>MAX_HEADER_VALUE_BYTES or len(selected)>=MAX_SIGNATURE_HEADERS:raise WhopIngressError("invalid webhook")
   try:name=raw_name.decode("ascii","strict");value=raw_value.decode("utf-8","strict")
   except UnicodeError:raise WhopIngressError("invalid webhook") from None
   selected.append((name,value))
 if not selected:raise WhopIngressError("invalid webhook")
 result={}
 for name,value in selected:
  key=name.casefold()
  if key in result:raise WhopIngressError("invalid webhook")
  result[key]=value
 return result

def bounded_request(raw_body:bytes,headers:Mapping[str,str])->tuple[bytes,dict[str,str]]:
 if type(raw_body) is not bytes or not raw_body or len(raw_body)>MAX_BODY_BYTES:raise WhopIngressError("invalid webhook")
 selected=[]
 for name,value in headers.items():
  if _SIGNATURE_HEADER.search(name):
   try:n=name.encode("ascii");v=value.encode("utf-8","strict")
   except (UnicodeError,AttributeError):raise WhopIngressError("invalid webhook") from None
   if not n or len(n)>MAX_HEADER_NAME_BYTES or not v or len(v)>MAX_HEADER_VALUE_BYTES:raise WhopIngressError("invalid webhook")
   selected.append((name.lower(),value))
 if not selected or len(selected)>MAX_SIGNATURE_HEADERS:raise WhopIngressError("invalid webhook")
 folded={}
 for name,value in selected:
  key=name.casefold()
  if key in folded:raise WhopIngressError("invalid webhook")
  folded[key]=value
 return raw_body,folded

def parse_verified_event(payload:bytes)->VerifiedWhopEvent:
 if type(payload) is not bytes or not payload or len(payload)>MAX_VERIFIED_BODY_BYTES:raise WhopIngressError("invalid webhook")
 def pairs(items):
  result={};folded=set()
  for key,value in items:
   if type(key) is not str or key.casefold() in folded:raise WhopIngressError("invalid webhook")
   folded.add(key.casefold());result[key]=value
  return result
 try:value=json.loads(payload,object_pairs_hook=pairs)
 except (ValueError,TypeError,json.JSONDecodeError) as error:raise WhopIngressError("invalid webhook") from error
 keys={"event_id","kind","occurred_at","order_id","provider_order_ref","provider_payment_ref"}
 if type(value) is not dict or set(value)!=keys or any(type(value[k]) is not str for k in keys):raise WhopIngressError("invalid webhook")
 if value["kind"] not in _KINDS:raise WhopIngressError("invalid webhook")
 for key in ("event_id","order_id","provider_order_ref","provider_payment_ref"):
  if not _TOKEN.fullmatch(value[key]):raise WhopIngressError("invalid webhook")
 try:stamp=datetime.fromisoformat(value["occurred_at"])
 except ValueError:raise WhopIngressError("invalid webhook") from None
 if stamp.tzinfo!=timezone.utc or stamp.isoformat()!=value["occurred_at"]:raise WhopIngressError("invalid webhook")
 return VerifiedWhopEvent(**value)

# Official SDK adapter.  This remains caller-injected; no environment or
# production composition code constructs it.
import base64
import importlib
from decimal import Decimal,InvalidOperation
from typing import Callable,Any

_OFFICIAL_HEADERS={"webhook-id","webhook-timestamp","webhook-signature"}
_OFFICIAL_EVENT_KEYS={"id","api_version","type","timestamp","company_id","data"}

class OfficialWhopVerifier:
 """Verify with ``whop-sdk`` and normalize one documented event shape.

 The SDK is imported only on the first call.  Refund/dispute events are
 intentionally unsupported because this source slice has no reviewed exact
 linkage schema for those event data objects.
 """
 __slots__=("_api_key","_webhook_secret","_company_id","_product_id","_plan_id","_checkout_id","_currency","_total","_sdk_factory")
 def __init__(self,*,api_key:str,webhook_secret:str,company_id:str,
              expected_currency:str,expected_total:str,
              product_id:str|None=None,plan_id:str|None=None,
              checkout_configuration_id:str|None=None,
              sdk_factory:Callable[...,Any]|None=None):
  values=(api_key,webhook_secret,company_id,expected_currency,expected_total)
  if any(type(v) is not str or not v for v in values):raise WhopIngressError("official Whop configuration unavailable")
  if not _TOKEN.fullmatch(company_id) or not re.fullmatch(r"[a-z]{3}",expected_currency):raise WhopIngressError("official Whop configuration unavailable")
  identifiers=(product_id,plan_id,checkout_configuration_id)
  if not any(identifiers) or any(v is not None and (type(v) is not str or not _TOKEN.fullmatch(v)) for v in identifiers):raise WhopIngressError("official Whop configuration unavailable")
  try:total=Decimal(expected_total)
  except InvalidOperation:raise WhopIngressError("official Whop configuration unavailable") from None
  if not total.is_finite() or total<=0:raise WhopIngressError("official Whop configuration unavailable")
  self._api_key=api_key;self._webhook_secret=webhook_secret;self._company_id=company_id
  self._currency=expected_currency;self._total=total;self._product_id=product_id
  self._plan_id=plan_id;self._checkout_id=checkout_configuration_id;self._sdk_factory=sdk_factory

 def _client(self):
  factory=self._sdk_factory
  if factory is None:
   try:factory=getattr(importlib.import_module("whop_sdk"),"Whop")
   except (ImportError,AttributeError):raise WhopIngressError("official Whop verifier unavailable") from None
  try:
   key=base64.b64encode(self._webhook_secret.encode("utf-8","strict")).decode("ascii")
   return factory(api_key=self._api_key,webhook_key=key)
  except Exception:raise WhopIngressError("official Whop verifier unavailable") from None

 def verify(self,raw_body:bytes,signature_headers:Mapping[str,str])->bytes:
  bounded,headers=bounded_request(raw_body,signature_headers)
  if set(headers)!=_OFFICIAL_HEADERS:raise WhopIngressError("invalid webhook")
  try:text=bounded.decode("utf-8","strict")
  except UnicodeError:raise WhopIngressError("invalid webhook") from None
  try:self._client().webhooks.unwrap(text,headers=dict(headers))
  except WhopIngressError:raise
  except Exception:raise WhopIngressError("invalid webhook") from None
  value=_strict_official_json(text)
  normalized=self._normalize_payment(value)
  return json.dumps(normalized,separators=(",",":"),sort_keys=True).encode("utf-8")

 def _normalize_payment(self,value:object)->dict[str,str]:
  if type(value) is not dict or set(value)!=_OFFICIAL_EVENT_KEYS:raise WhopIngressError("invalid webhook")
  if value["api_version"]!="v1" or value["type"]!="payment.succeeded":raise WhopIngressError("invalid webhook")
  if value["company_id"]!=self._company_id:raise WhopIngressError("invalid webhook")
  event_id=value["id"];data=value["data"]
  if type(event_id) is not str or not _TOKEN.fullmatch(event_id) or type(data) is not dict:raise WhopIngressError("invalid webhook")
  payment_id=data.get("id");status=data.get("status");currency=data.get("currency");metadata=data.get("metadata")
  if type(payment_id) is not str or not _TOKEN.fullmatch(payment_id) or status!="succeeded" or currency!=self._currency or type(metadata) is not dict:raise WhopIngressError("invalid webhook")
  order_id=metadata.get("order_id")
  if type(order_id) is not str or not _TOKEN.fullmatch(order_id):raise WhopIngressError("invalid webhook")
  total=data.get("total")
  if type(total) not in (int,Decimal) or isinstance(total,bool) or Decimal(total)!=self._total:raise WhopIngressError("invalid webhook")
  matched=[]
  if self._product_id is not None:
   product=data.get("product")
   if type(product) is not dict or product.get("id")!=self._product_id:raise WhopIngressError("invalid webhook")
   matched.append(self._product_id)
  if self._plan_id is not None:
   plan=data.get("plan")
   if type(plan) is not dict or plan.get("id")!=self._plan_id:raise WhopIngressError("invalid webhook")
   matched.append(self._plan_id)
  if self._checkout_id is not None:
   if data.get("checkout_configuration_id")!=self._checkout_id:raise WhopIngressError("invalid webhook")
   matched.append(self._checkout_id)
  stamp=_official_timestamp(value["timestamp"])
  return {"event_id":event_id,"kind":"paid","occurred_at":stamp,"order_id":order_id,
          "provider_order_ref":matched[-1],"provider_payment_ref":payment_id}

def _strict_official_json(text:str)->object:
 def pairs(items):
  result={};folded=set()
  for key,value in items:
   if type(key) is not str or key.casefold() in folded:raise WhopIngressError("invalid webhook")
   folded.add(key.casefold());result[key]=value
  return result
 try:return json.loads(text,object_pairs_hook=pairs,parse_float=Decimal,parse_int=int)
 except (ValueError,TypeError,json.JSONDecodeError,WhopIngressError) as error:
  if isinstance(error,WhopIngressError):raise
  raise WhopIngressError("invalid webhook") from None

def _official_timestamp(value:object)->str:
 if type(value) is not str or not value.endswith("Z"):raise WhopIngressError("invalid webhook")
 try:stamp=datetime.fromisoformat(value[:-1]+"+00:00")
 except ValueError:raise WhopIngressError("invalid webhook") from None
 if stamp.tzinfo!=timezone.utc:raise WhopIngressError("invalid webhook")
 return stamp.isoformat()
