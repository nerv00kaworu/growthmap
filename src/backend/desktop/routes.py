import json, os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import ProviderConfig
from pydantic import BaseModel
from desktop.entitlements import LICENSE_PATH, _atomic_json, checkpoint_current_entitlement, peek_current_entitlement, initialize_trial, verify_document, verify_revocation_assertion, strict_json_loads
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
    if before.state != "trial" or not before.valid or not before.mutations_allowed:
        raise HTTPException(403,"Lifecycle checkpoint requires an active writable trial")
    return checkpoint_current_entitlement().public()
@router.post("/trial/start")
def start_trial(body: TrialStartIn, x_growthmap_fresh_install: str | None=Header(None)):
    if x_growthmap_fresh_install != "1" or os.getenv("GROWTHMAP_FRESH_INSTALL") != "1" or verdict_mode() != "fresh":
        raise HTTPException(403,"Fresh-install authorization required")
    initialize_trial(started_at=body.started_at, installation_id=body.installation_id)
    return peek_current_entitlement().public()
async def _strict_document(request: Request) -> dict:
    try:
        envelope=strict_json_loads((await request.body()).decode("utf-8"))
        if not isinstance(envelope,dict) or set(envelope)!={"document"} or not isinstance(envelope["document"],dict): raise ValueError()
        return envelope["document"]
    except Exception: raise HTTPException(400,"Duplicate, case-colliding, or invalid JSON")

@router.post("/license/import")
async def import_license(request: Request):
    document=await _strict_document(request);value = verify_document(document)
    if not value.valid: raise HTTPException(400, f"License rejected: {value.reason}")
    _atomic_json(LICENSE_PATH, document)
    return value.public()

@router.post("/revocation/verify")
async def verify_revocation(request: Request):
    document=await _strict_document(request)
    try: current=verify_document(strict_json_loads(LICENSE_PATH.read_text("utf-8")))
    except Exception: current=None
    if current is None or current.state!="paid" or not current.valid or not current.license_id: raise HTTPException(400,"An active matching license is required")
    try: verify_revocation_assertion(document,current.license_id,license_issued_at=strict_json_loads(LICENSE_PATH.read_text("utf-8")).get("issued_at"))
    except Exception as error: raise HTTPException(400,f"Revocation rejected: {error}")
    return {"accepted":True,"license_id":current.license_id,"sequence":document["sequence"]}
