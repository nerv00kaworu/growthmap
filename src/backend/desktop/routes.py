import json, os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import ProviderConfig
from pydantic import BaseModel
from desktop.entitlements import LICENSE_PATH, _atomic_json, checkpoint_current_entitlement, peek_current_entitlement, initialize_trial, verify_document, verify_revocation_assertion, strict_json_loads, stable_json_file
from desktop.startup_verdict import effective_entitlement, verdict_mode
from desktop.secrets import put, delete
router = APIRouter(prefix="/desktop")
class SecretIn(BaseModel): api_key: str
class LicenseIn(BaseModel): document: dict
class RevocationIn(BaseModel): document: dict
class TrialStartIn(BaseModel): started_at: str; installation_id: str
@router.put("/secrets/{provider_id}", status_code=204)
async def set_secret(provider_id: str, body: SecretIn, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    if provider.provider_type == "mock":
        raise HTTPException(400, "Mock provider does not use an API key")
    put(provider_id, body.api_key)

@router.delete("/secrets/{provider_id}", status_code=204)
async def remove_secret(provider_id: str, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    delete(provider_id)
@router.get("/entitlement")
def entitlement(): return effective_entitlement().public()
@router.post("/entitlement/checkpoint")
def entitlement_checkpoint():
    before=effective_entitlement()
    if before.state != "free" or not before.valid or not before.mutations_allowed:
        raise HTTPException(403,"Lifecycle checkpoint requires an active writable Free entitlement")
    return checkpoint_current_entitlement().public()
@router.post("/trial/start")
def start_trial(body: TrialStartIn, x_growthmap_fresh_install: str | None=Header(None)):
    if x_growthmap_fresh_install != "1" or os.getenv("GROWTHMAP_FRESH_INSTALL") != "1" or verdict_mode() != "fresh":
        raise HTTPException(403,"Fresh-install authorization required")
    initialize_trial(started_at=body.started_at, installation_id=body.installation_id)
    return peek_current_entitlement().public()
@router.post("/license/import")
async def import_license(request: Request):
    raw=await request.body()
    if len(raw)>65536: raise HTTPException(413,"License document too large")
    try:
        body=strict_json_loads(raw.decode("utf-8"))
        if set(body)!={"document"} or not isinstance(body["document"],dict): raise ValueError("shape")
        document=body["document"]
    except Exception: raise HTTPException(400,"License JSON must have unique case-distinct keys")
    value=verify_document(document,device_public_key=os.getenv("GROWTHMAP_DEVICE_PUBLIC_KEY"))
    if not value.valid: raise HTTPException(400,f"License rejected: {value.reason}")
    # A different license cannot silently replace an already valid identity. Authenticated
    # recovery/deactivation belongs at the authority boundary, not in this local import route.
    if LICENSE_PATH.exists():
        try:
            if LICENSE_PATH.is_symlink() or not LICENSE_PATH.is_file(): raise HTTPException(409,"Installed license requires authenticated recovery")
            existing_doc=stable_json_file(LICENSE_PATH)
            existing_id=existing_doc.get("license_id")
            if not isinstance(existing_id,str) or not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",existing_id): raise HTTPException(409,"Installed license requires authenticated recovery")
            if existing_id!=value.license_id: raise HTTPException(409,"License substitution requires authenticated recovery")
            existing=verify_document(existing_doc,device_public_key=os.getenv("GROWTHMAP_DEVICE_PUBLIC_KEY"))
            if existing.valid and existing_doc==document:return existing.public()
        except HTTPException:raise
        except Exception:raise HTTPException(409,"Installed license requires authenticated recovery")
    parent=LICENSE_PATH.parent
    try:
        parent.mkdir(parents=True,exist_ok=True,mode=0o700);pst=parent.lstat()
        if not pst.is_dir() or parent.is_symlink(): raise ValueError("unsafe")
        os.chmod(parent,0o700)
        if LICENSE_PATH.exists() and (LICENSE_PATH.is_symlink() or not LICENSE_PATH.is_file()): raise ValueError("unsafe")
    except Exception: raise HTTPException(400,"Unsafe license destination")
    _atomic_json(LICENSE_PATH,document);return value.public()

@router.post("/revocation/verify")
async def verify_revocation(request: Request):
    try: body=strict_json_loads((await request.body()).decode("utf-8")); document=body["document"]
    except Exception: raise HTTPException(400,"Revocation JSON must have unique case-distinct keys")
    try: license_doc=strict_json_loads(LICENSE_PATH.read_text("utf-8"));current=verify_document(license_doc,device_public_key=os.getenv("GROWTHMAP_DEVICE_PUBLIC_KEY"))
    except Exception: current=None
    if current is None or current.state not in {"paid","paid_legacy"} or not current.valid or not current.license_id: raise HTTPException(400,"A matching license is required")
    try: verify_revocation_assertion(document,current.license_id,issued_at=license_doc["issued_at"])
    except Exception as error: raise HTTPException(400,f"Revocation rejected: {error}")
    return {"accepted":True,"license_id":current.license_id,"sequence":document["sequence"]}
