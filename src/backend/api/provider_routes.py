"""Provider configuration API routes."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from models.schemas import ProviderConfigCreate, ProviderConfigOut, ProviderConfigUpdate
from services.exceptions import NotFoundError, ValidationError
from services.provider_service import (
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    update_provider,
)

router = APIRouter(tags=["providers"])


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ValidationError):
        raise HTTPException(status_code=400, detail=str(error))
    raise error


def _redact_provider(provider):
    provider.settings = {
        key: ("***" if key == "api_key" and value else value)
        for key, value in (provider.settings or {}).items()
    }
    return provider


@router.get("/providers", response_model=list[ProviderConfigOut])
async def list_provider_configs(db: AsyncSession = Depends(get_db)):
    return [_redact_provider(provider) for provider in await list_providers(db)]


@router.post("/providers", response_model=ProviderConfigOut, status_code=status.HTTP_201_CREATED)
async def create_provider_config(data: ProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        return _redact_provider(await create_provider(data, db))
    except (NotFoundError, ValidationError) as error:
        _raise_http_error(error)


@router.get("/providers/{provider_id}", response_model=ProviderConfigOut)
async def get_provider_config(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return _redact_provider(await get_provider(provider_id, db))
    except (NotFoundError, ValidationError) as error:
        _raise_http_error(error)


@router.patch("/providers/{provider_id}", response_model=ProviderConfigOut)
async def update_provider_config(
    provider_id: str,
    data: ProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
): 
    try:
        return _redact_provider(await update_provider(provider_id, data, db))
    except (NotFoundError, ValidationError) as error:
        _raise_http_error(error)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(provider_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_provider(provider_id, db)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except (NotFoundError, ValidationError) as error:
        _raise_http_error(error)
