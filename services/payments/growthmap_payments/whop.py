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
