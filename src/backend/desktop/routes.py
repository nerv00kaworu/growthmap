import json, os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from models.models import ProviderConfig
from pydantic import BaseModel
from desktop.entitlements import LICENSE_PATH, current_entitlement, verify_document
from desktop.secrets import put, delete
router = APIRouter(prefix="/desktop")
class SecretIn(BaseModel): api_key: str
class LicenseIn(BaseModel): document: dict
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
def entitlement(): return current_entitlement().__dict__
@router.post("/license/import")
def import_license(body: LicenseIn):
    value = verify_document(body.document)
    if not value.valid: raise HTTPException(400, f"License rejected: {value.reason}")
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = LICENSE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(body.document, indent=2), "utf-8")
    os.chmod(temp, 0o600); temp.replace(LICENSE_PATH)
    return value.__dict__
