"""Service helpers for provider configuration CRUD."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ProviderConfig
from models.schemas import ProviderConfigCreate, ProviderConfigUpdate
from services.exceptions import NotFoundError, ValidationError


async def list_providers(db: AsyncSession) -> list[ProviderConfig]:
    result = await db.execute(
        select(ProviderConfig).order_by(ProviderConfig.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_provider(provider_id: str, db: AsyncSession) -> ProviderConfig:
    provider = await db.get(ProviderConfig, provider_id)
    if provider is None:
        raise NotFoundError("Provider not found")
    return provider


async def create_provider(data: ProviderConfigCreate, db: AsyncSession) -> ProviderConfig:
    await _ensure_unique_name(data.name, db)
    provider = ProviderConfig(**data.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def update_provider(
    provider_id: str,
    data: ProviderConfigUpdate,
    db: AsyncSession,
) -> ProviderConfig:
    provider = await get_provider(provider_id, db)
    updates = data.model_dump(exclude_unset=True)

    new_name = updates.get("name")
    if new_name and new_name != provider.name:
        await _ensure_unique_name(new_name, db)

    for key, value in updates.items():
        setattr(provider, key, value)

    await db.commit()
    await db.refresh(provider)
    return provider


async def delete_provider(provider_id: str, db: AsyncSession) -> None:
    provider = await get_provider(provider_id, db)
    await db.delete(provider)
    await db.commit()


async def _ensure_unique_name(name: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(ProviderConfig).where(ProviderConfig.name == name)
    )
    if result.scalar_one_or_none() is not None:
        raise ValidationError("Provider name already exists")
