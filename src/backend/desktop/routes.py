import json, os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import ProviderConfig
from pydantic import BaseModel
from desktop.entitlements import LICENSE_PATH, _atomic_json, checkpoint_current_entitlement, peek_current_entitlement, initialize_trial, verify_document
from desktop.startup_verdict import effective_entitlement, verdict_mode
from desktop.secrets import put, delete
router = APIRouter(prefix="/desktop")
class SecretIn(BaseModel): api_key: str
class LicenseIn(BaseModel): document: dict
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
@router.post("/license/import")
def import_license(body: LicenseIn):
    value = verify_document(body.document)
    if not value.valid: raise HTTPException(400, f"License rejected: {value.reason}")
    _atomic_json(LICENSE_PATH, body.document)
    return value.public()
