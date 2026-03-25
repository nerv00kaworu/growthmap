"""Tests for AI response parsing and malformed payload handling."""
import json
from types import SimpleNamespace

import httpx

from ai import provider, routes


class TestParseJsonResponse:
    def test_parse_json_response_handles_markdown_wrapped_json(self):
        payload = """```json
        [{\"title\": \"Child\", \"summary\": \"Summary\", \"node_type\": \"idea\"}]
        ```"""

        result = provider.parse_json_response(payload)

        assert isinstance(result, list)
        assert result[0]["title"] == "Child"


class TestAiRouteMalformedResponses:
    async def test_expand_route_rejects_wrong_structure_payload(self, client, monkeypatch):
        project_resp = await client.post("/api/projects", json={"name": "Project", "description": "desc", "goal": "goal"})
        project = project_resp.json()

        async def fake_llm_complete(*args, **kwargs):
            return json.dumps({"title": "not-a-list"})

        monkeypatch.setattr(routes, "llm_complete", fake_llm_complete)

        resp = await client.post(
            "/api/ai/expand",
            json={"node_id": project["root_node_id"], "count": 2, "mode": "explore"},
        )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "LLM error: LLM returned an invalid suggestions payload"

    async def test_deepen_route_rejects_missing_expected_fields(self, client, monkeypatch):
        project_resp = await client.post("/api/projects", json={"name": "Project", "description": "desc", "goal": "goal"})
        project = project_resp.json()

        async def fake_llm_complete(*args, **kwargs):
            return json.dumps({"content_blocks": []})

        monkeypatch.setattr(routes, "llm_complete", fake_llm_complete)

        resp = await client.post(
            "/api/ai/deepen",
            json={"node_id": project["root_node_id"]},
        )

        assert resp.status_code == 500
        assert "enriched_summary" in resp.json()["detail"]

    async def test_expand_route_rejects_non_mapping_suggestions(self, client, monkeypatch):
        project_resp = await client.post("/api/projects", json={"name": "Project", "description": "desc", "goal": "goal"})
        project = project_resp.json()

        async def fake_llm_complete(*args, **kwargs):
            return json.dumps(["bad-item"])

        monkeypatch.setattr(routes, "llm_complete", fake_llm_complete)

        resp = await client.post(
            "/api/ai/expand",
            json={"node_id": project["root_node_id"], "count": 1, "mode": "explore"},
        )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "LLM returned malformed expand payload"


class TestLlmCompleteRetryBehavior:
    async def test_llm_complete_retries_once_on_timeout(self, monkeypatch):
        attempts = {"count": 0}
        seen_timeout = {"value": None}

        monkeypatch.setattr(
            provider,
            "get_provider_config",
            lambda: ("https://example.com", "test-key", "test-model"),
        )

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                attempts["count"] += 1
                seen_timeout["value"] = kwargs.get("timeout")
                if attempts["count"] == 1:
                    raise httpx.ReadTimeout("timed out")
                return FakeResponse()

        async def fake_sleep(_seconds: float):
            return None

        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(provider, "asyncio", SimpleNamespace(sleep=fake_sleep), raising=False)

        result = await provider.llm_complete("system", "user")

        assert result == "ok"
        assert attempts["count"] == 2
        assert isinstance(seen_timeout["value"], httpx.Timeout)
        assert seen_timeout["value"].connect == 10.0

    async def test_llm_complete_retries_once_on_retryable_status(self, monkeypatch):
        attempts = {"count": 0}
        seen_timeout = {"value": None}

        monkeypatch.setattr(
            provider,
            "get_provider_config",
            lambda: ("https://example.com", "test-key", "test-model"),
        )

        class FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    request = httpx.Request("POST", "https://example.com/chat/completions")
                    raise httpx.HTTPStatusError("boom", request=request, response=self)

            def json(self):
                return self._payload

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                attempts["count"] += 1
                seen_timeout["value"] = kwargs.get("timeout")
                if attempts["count"] == 1:
                    return FakeResponse(503, {"error": "unavailable"})
                return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

        async def fake_sleep(_seconds: float):
            return None

        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(provider, "asyncio", SimpleNamespace(sleep=fake_sleep), raising=False)

        result = await provider.llm_complete("system", "user")

        assert result == "ok"
        assert attempts["count"] == 2
        assert isinstance(seen_timeout["value"], httpx.Timeout)
        assert seen_timeout["value"].connect == 10.0
