"""Strict offline, fail-closed license verification. No private signing material belongs here."""
import base64, json, os, re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
FREE_LIMIT=2; EDITIONS={"personal","pro","studio"}; REQUIRED={"edition","license_id","max_active_projects","signature"}; ALLOWED=REQUIRED|{"expires_at"}
PUBLIC_KEY_PATH=Path(os.getenv("GROWTHMAP_LICENSE_PUBLIC_KEY",Path(__file__).with_name("license_public_key.pem"))); LICENSE_PATH=Path(os.getenv("GROWTHMAP_LICENSE_FILE",Path.home()/".growthmap"/"license.json"))
@dataclass(frozen=True)
class Entitlement:
 edition:str="free";license_id:str|None=None;max_active_projects:int|None=FREE_LIMIT;valid:bool=False;reason:str="no_license"
def canonical_payload(doc:dict[str,Any])->bytes:
 fields={k:doc[k] for k in ("edition","license_id","expires_at","max_active_projects") if k in doc}
 return json.dumps(fields,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def verify_document(doc:dict[str,Any],public_key_path:Path=PUBLIC_KEY_PATH)->Entitlement:
 try:
  if not isinstance(doc,dict) or set(doc)-ALLOWED or not REQUIRED<=set(doc):return Entitlement(reason="invalid_document")
  if doc["edition"] not in EDITIONS:return Entitlement(reason="invalid_edition")
  if not isinstance(doc["license_id"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",doc["license_id"]):return Entitlement(reason="invalid_license_id")
  expires=doc.get("expires_at")
  if expires is not None:
   if not isinstance(expires,str):return Entitlement(reason="invalid_expiry")
   expiry=datetime.fromisoformat(expires.replace("Z","+00:00"))
   if expiry.tzinfo is None:return Entitlement(reason="invalid_expiry")
   if expiry<=datetime.now(timezone.utc):return Entitlement(reason="expired")
  limit=doc["max_active_projects"]
  if limit is not None and (isinstance(limit,bool) or not isinstance(limit,int) or limit<FREE_LIMIT):return Entitlement(reason="invalid_limit")
  raw=public_key_path.read_bytes()
  if b"REPLACE_WITH" in raw:return Entitlement(reason="placeholder_public_key")
  key=serialization.load_pem_public_key(raw)
  if not isinstance(key,Ed25519PublicKey):return Entitlement(reason="invalid_public_key")
  key.verify(base64.b64decode(doc["signature"],validate=True),canonical_payload(doc))
  return Entitlement(doc["edition"],doc["license_id"],limit,True,"valid")
 except (OSError,ValueError,TypeError,InvalidSignature):return Entitlement(reason="invalid_signature")
def current_entitlement()->Entitlement:
 try:return verify_document(json.loads(LICENSE_PATH.read_text("utf-8")))
 except (OSError,ValueError):return Entitlement()
