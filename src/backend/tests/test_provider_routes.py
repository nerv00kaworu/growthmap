"""Tests for provider config API routes."""


def build_provider_payload(**overrides) -> dict:
    payload = {
        "name": "API Provider",
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


class TestProviderRoutes:
    async def test_create_provider_returns_201(self, client):
        response = await client.post("/api/providers", json=build_provider_payload())

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "API Provider"
        assert data["provider_type"] == "openai-compatible"
        assert data["settings"]["api_key"] == "***"

    async def test_list_providers_returns_created_items(self, client):
        await client.post("/api/providers", json=build_provider_payload(name="Provider One"))
        await client.post(
            "/api/providers",
            json=build_provider_payload(name="Provider Two", endpoint="https://two.example/v1"),
        )

        response = await client.get("/api/providers")

        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == ["Provider Two", "Provider One"]

    async def test_get_provider_returns_404_for_missing_id(self, client):
        response = await client.get("/api/providers/missing-provider")

        assert response.status_code == 404
        assert response.json()["detail"] == "Provider not found"

    async def test_patch_provider_returns_updated_payload(self, client):
        created = await client.post("/api/providers", json=build_provider_payload())
        provider_id = created.json()["id"]

        response = await client.patch(
            f"/api/providers/{provider_id}",
            json={"model_name": "gpt-4.1", "enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == provider_id
        assert data["model_name"] == "gpt-4.1"
        assert data["enabled"] is False

    async def test_delete_provider_returns_204_and_removes_resource(self, client):
        created = await client.post("/api/providers", json=build_provider_payload())
        provider_id = created.json()["id"]

        delete_response = await client.delete(f"/api/providers/{provider_id}")
        fetch_response = await client.get(f"/api/providers/{provider_id}")

        assert delete_response.status_code == 204
        assert fetch_response.status_code == 404

    async def test_create_provider_returns_400_for_duplicate_name(self, client):
        await client.post("/api/providers", json=build_provider_payload())

        response = await client.post(
            "/api/providers",
            json=build_provider_payload(endpoint="https://duplicate.example/v1"),
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Provider name already exists"

    async def test_provider_reads_redact_stored_api_key(self, client):
        created = await client.post("/api/providers", json=build_provider_payload())
        provider_id = created.json()["id"]

        get_response = await client.get(f"/api/providers/{provider_id}")
        list_response = await client.get("/api/providers")

        assert get_response.status_code == 200
        assert get_response.json()["settings"]["api_key"] == "***"
        assert list_response.status_code == 200
        assert list_response.json()[0]["settings"]["api_key"] == "***"
