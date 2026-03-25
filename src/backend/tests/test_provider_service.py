"""Tests for provider service CRUD behavior."""
import pytest

from models.schemas import ProviderConfigCreate, ProviderConfigUpdate
from services.exceptions import NotFoundError, ValidationError
from services.provider_service import (
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    update_provider,
)


def build_provider_payload(**overrides) -> dict:
    payload = {
        "name": "Primary Provider",
        "provider_type": "openai-compatible",
        "endpoint": "https://providers.example/v1",
        "auth_type": "bearer",
        "model_name": "gpt-4.1-mini",
        "capabilities": ["expand", "deepen"],
        "cost_level": "medium",
        "enabled": True,
        "settings": {"api_key": "provider-secret"},
    }
    payload.update(overrides)
    return payload


class TestProviderService:
    async def test_create_and_list_providers(self, db_session):
        created = await create_provider(
            ProviderConfigCreate(**build_provider_payload()),
            db_session,
        )

        providers = await list_providers(db_session)

        assert len(providers) == 1
        assert providers[0].id == created.id
        assert providers[0].name == "Primary Provider"

    async def test_get_provider_raises_not_found_for_missing_id(self, db_session):
        with pytest.raises(NotFoundError, match="Provider not found"):
            await get_provider("missing-provider", db_session)

    async def test_create_provider_rejects_duplicate_name(self, db_session):
        await create_provider(ProviderConfigCreate(**build_provider_payload()), db_session)

        with pytest.raises(ValidationError, match="Provider name already exists"):
            await create_provider(
                ProviderConfigCreate(**build_provider_payload(endpoint="https://other.example/v1")),
                db_session,
            )

    async def test_update_provider_persists_partial_changes(self, db_session):
        created = await create_provider(ProviderConfigCreate(**build_provider_payload()), db_session)

        updated = await update_provider(
            created.id,
            ProviderConfigUpdate(model_name="gpt-4.1", enabled=False),
            db_session,
        )

        assert updated.id == created.id
        assert updated.model_name == "gpt-4.1"
        assert updated.enabled is False
        assert updated.endpoint == "https://providers.example/v1"

    async def test_delete_provider_removes_row(self, db_session):
        created = await create_provider(ProviderConfigCreate(**build_provider_payload()), db_session)

        await delete_provider(created.id, db_session)

        with pytest.raises(NotFoundError, match="Provider not found"):
            await get_provider(created.id, db_session)
