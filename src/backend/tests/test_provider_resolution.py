"""Tests for provider-backed AI configuration resolution."""
import json

from ai import provider, routes
from models.models import ProviderConfig


class TestProviderConfigResolution:
    async def test_get_provider_config_from_db_prefers_db_values(self, db_session, monkeypatch):
        provider_config = ProviderConfig(
            name="DB Provider",
            provider_type="openai-compatible",
            endpoint="https://db-provider.example/v1/",
            auth_type="bearer",
            model_name="db-model",
            settings={"api_key": "db-secret"},
        )
        db_session.add(provider_config)
        await db_session.commit()
        await db_session.refresh(provider_config)

        monkeypatch.setattr(provider, "LLM_BASE_URL", "https://env-provider.example/v1")
        monkeypatch.setattr(provider, "LLM_API_KEY", "env-secret")
        monkeypatch.setattr(provider, "LLM_MODEL", "env-model")

        base_url, api_key, model_name = await provider.get_provider_config_from_db(
            provider_config.id,
            db_session,
        )

        assert base_url == "https://db-provider.example/v1"
        assert api_key == "db-secret"
        assert model_name == "db-model"

    async def test_get_provider_config_from_db_falls_back_to_env_when_missing(self, db_session, monkeypatch):
        monkeypatch.setattr(provider, "LLM_BASE_URL", "https://env-provider.example/v1")
        monkeypatch.setattr(provider, "LLM_API_KEY", "env-secret")
        monkeypatch.setattr(provider, "LLM_MODEL", "env-model")

        base_url, api_key, model_name = await provider.get_provider_config_from_db(
            "missing-provider",
            db_session,
        )

        assert base_url == "https://env-provider.example/v1"
        assert api_key == "env-secret"
        assert model_name == "env-model"


class TestProviderAwareAiRoutes:
    async def test_expand_route_passes_provider_id_to_llm_complete(self, client, monkeypatch):
        project_resp = await client.post(
            "/api/projects",
            json={"name": "Project", "description": "desc", "goal": "goal"},
        )
        project = project_resp.json()
        captured = {}

        async def fake_llm_complete(*args, **kwargs):
            captured.update(kwargs)
            return json.dumps([
                {"title": "Child", "summary": "Summary", "node_type": "idea"},
            ])

        monkeypatch.setattr(routes, "llm_complete", fake_llm_complete)

        response = await client.post(
            "/api/ai/expand",
            json={
                "node_id": project["root_node_id"],
                "count": 1,
                "mode": "explore",
                "provider_id": "provider-123",
            },
        )

        assert response.status_code == 200
        assert captured["provider_id"] == "provider-123"
        assert captured["db"] is not None

    async def test_deepen_route_passes_provider_id_to_llm_complete(self, client, monkeypatch):
        project_resp = await client.post(
            "/api/projects",
            json={"name": "Project", "description": "desc", "goal": "goal"},
        )
        project = project_resp.json()
        captured = {}

        async def fake_llm_complete(*args, **kwargs):
            captured.update(kwargs)
            return json.dumps(
                {
                    "enriched_summary": "More detail",
                    "content_blocks": [{"title": "Block", "body": "Body", "block_type": "notes"}],
                }
            )

        monkeypatch.setattr(routes, "llm_complete", fake_llm_complete)

        response = await client.post(
            "/api/ai/deepen",
            json={
                "node_id": project["root_node_id"],
                "instruction": "go deeper",
                "provider_id": "provider-456",
            },
        )

        assert response.status_code == 200
        assert captured["provider_id"] == "provider-456"
        assert captured["db"] is not None
