import asyncio
import pytest
from fastapi import HTTPException
from ai import routes

REQUEST_ID = "0123456789abcdef"
PRIVATE_PROVIDER_SENTINEL = "private-provider.example.invalid"
PRIVATE_MODEL_SENTINEL = "private-model-sentinel"

class DB: pass

@pytest.mark.asyncio
async def test_connection_operation_timeout_returns_fixed_safe_diagnostic(monkeypatch):
    cancelled = asyncio.Event()
    async def config(*_): return type("Config", (), {"provider":PRIVATE_PROVIDER_SENTINEL, "model":PRIVATE_MODEL_SENTINEL})(), "provider"
    async def hanging(_):
        try: await asyncio.Future()
        finally: cancelled.set()
    monkeypatch.setattr(routes, "_to_llm_config", config)
    monkeypatch.setattr(routes, "_request_id", lambda: REQUEST_ID)
    monkeypatch.setattr(routes, "TEST_CONNECTION_TIMEOUT_SECONDS", 0.001)
    import ai.providers.registry as registry
    monkeypatch.setattr(registry, "test_connection", hanging)
    req=routes.TestConnectionRequest(provider_id="provider", provider_revision=1, selection_revision=1)
    with pytest.raises(HTTPException) as caught: await routes.test_connection(req, DB())
    assert cancelled.is_set()
    assert caught.value.status_code == 504
    assert caught.value.detail == {"code":"LLM_TIMEOUT", "message":"The AI provider did not respond within the maximum wait. Please retry.", "request_id":REQUEST_ID}
    public_detail = repr(caught.value.detail)
    assert PRIVATE_PROVIDER_SENTINEL not in public_detail
    assert PRIVATE_MODEL_SENTINEL not in public_detail

@pytest.mark.asyncio
async def test_connection_success_keeps_request_id_and_elapsed(monkeypatch):
    async def config(*_): return type("Config", (), {"provider":"mock", "model":"m"})(), "provider"
    async def success(_): return {"ok":True,"provider":"mock","model":"m","message":"Mock provider ready"}
    monkeypatch.setattr(routes, "_to_llm_config", config)
    monkeypatch.setattr(routes, "_request_id", lambda: REQUEST_ID)
    import ai.providers.registry as registry
    monkeypatch.setattr(registry, "test_connection", success)
    req=routes.TestConnectionRequest(provider_id="provider", provider_revision=1, selection_revision=1)
    value=await routes.test_connection(req, DB())
    assert value.ok is True and value.code == "OK" and value.request_id == REQUEST_ID
    assert value.elapsed_ms >= 0
