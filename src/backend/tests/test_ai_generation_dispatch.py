import asyncio

import httpx
import pytest

from ai import routes
from ai.providers import registry
from ai.providers.base import LLMConfig
from ai.providers.openai_compatible import OpenAICompatibleProvider


VALID_RESPONSE = {"choices": [{"message": {"content": "ok"}}]}


class Response:
    def __init__(self, status_code=200, value=VALID_RESPONSE):
        self.status_code = status_code
        self.value = value
        self.request = httpx.Request("POST", "https://private.invalid/chat/completions")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "private upstream body must not be exposed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self.value


class Client:
    behavior = None
    calls = 0
    timeout = None

    def __init__(self, *, timeout):
        type(self).timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, *_args, **_kwargs):
        type(self).calls += 1
        behavior = type(self).behavior
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return await behavior()
        return behavior


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    Client.behavior = Response()
    Client.calls = 0
    Client.timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", Client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("private timeout detail"),
        Response(429),
        Response(500),
        Response(502),
        Response(503),
        Response(504),
    ],
)
async def test_dispatched_generation_is_never_retried(failure):
    Client.behavior = failure
    with pytest.raises((httpx.ReadTimeout, httpx.HTTPStatusError)):
        await OpenAICompatibleProvider(api_key="private-key").complete("private prompt", "private input")
    assert Client.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_seconds", [90, 120])
async def test_slow_reply_within_operation_timeout_succeeds_and_reaches_client(timeout_seconds):
    async def slow_success():
        await asyncio.sleep(0.01)
        return Response()

    Client.behavior = slow_success
    result = await OpenAICompatibleProvider(api_key="private-key").complete(
        "private prompt", "private input", response_timeout_seconds=timeout_seconds,
    )
    assert result == "ok"
    assert Client.calls == 1
    assert Client.timeout.read == timeout_seconds
    assert Client.timeout.write == timeout_seconds
    assert Client.timeout.pool == timeout_seconds
    assert Client.timeout.connect == 10


@pytest.mark.asyncio
async def test_total_deadline_cancels_active_completion_after_one_dispatch():
    dispatched = 0
    cancelled = asyncio.Event()

    class DripFeedProvider:
        async def complete(self, *_args, **_kwargs):
            nonlocal dispatched
            dispatched += 1
            try:
                # Repeated activity would remain below an HTTP inactivity
                # timeout, but must not extend the total operation deadline.
                while True:
                    await asyncio.sleep(0)
            finally:
                cancelled.set()

    with pytest.raises(TimeoutError):
        await routes._complete_with_deadline(
            DripFeedProvider(), "system", "user", model="model",
            timeout_seconds=0.001,
        )
    assert cancelled.is_set()
    assert dispatched == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [None, True, False, "60", float("nan"), float("inf"), -float("inf"), 0, -1, 120.0001],
)
async def test_invalid_response_timeout_rejected_before_dispatch(invalid):
    with pytest.raises(ValueError, match="Response timeout"):
        await OpenAICompatibleProvider(api_key="private-key").complete(
            "private prompt", "private input", response_timeout_seconds=invalid,
        )
    assert Client.calls == 0
    assert Client.timeout is None  # AsyncClient was not constructed.


@pytest.mark.asyncio
async def test_arbitrarily_huge_integer_timeout_rejected_before_client_construction():
    with pytest.raises(ValueError, match="Response timeout"):
        await OpenAICompatibleProvider(api_key="private-key").complete(
            "private prompt", "private input", response_timeout_seconds=10**10000,
        )
    assert Client.calls == 0
    assert Client.timeout is None


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [0.001, 1, 60.0, 120])
async def test_valid_response_timeout_dispatches_once(valid):
    assert await OpenAICompatibleProvider(api_key="private-key").complete(
        "private prompt", "private input", response_timeout_seconds=valid,
    ) == "ok"
    assert Client.calls == 1


@pytest.mark.asyncio
async def test_test_connection_uses_short_bounded_single_dispatch(monkeypatch):
    calls = []

    class Provider:
        async def complete(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "OK"

    monkeypatch.setattr(registry, "get_provider", lambda _config: Provider())
    result = await registry.test_connection(
        LLMConfig(provider="openai_compatible", api_key="private-key", model="model")
    )
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][1]["max_tokens"] == 10
    assert calls[0][1]["response_timeout_seconds"] == 60
    assert calls[0][1]["response_timeout_seconds"] < routes.TEST_CONNECTION_TIMEOUT_SECONDS


class DB:
    async def get(self, *_):
        return None


@pytest.mark.asyncio
async def test_routes_select_expand_deepen_and_chat_timeouts(monkeypatch):
    calls = []

    class Provider:
        async def complete(self, system, user, **kwargs):
            calls.append(kwargs["response_timeout_seconds"])
            if "enriched_summary" in system:
                return '{"enriched_summary":"summary","content_blocks":[{"title":"a","body":"b","block_type":"paragraph"},{"title":"c","body":"d","block_type":"todo"}]}'
            if "node_type" in system:
                return '[{"title":"child","summary":"detail","node_type":"task"}]'
            return "reply"

    context = {
        "ancestor_path": [], "children": [], "siblings": [],
        "current_node": {"title": "node"},
    }

    async def build_context(*_):
        return context

    async def config(*_):
        return LLMConfig(provider="mock", model="model"), "provider"

    monkeypatch.setattr(routes, "build_node_context", build_context)
    monkeypatch.setattr(routes, "_to_llm_config", config)
    monkeypatch.setattr(routes, "get_provider", lambda _config: Provider())

    common = {"node_id": "node", "provider_id": "provider", "provider_revision": 1, "selection_revision": 1}
    await routes.expand_node(routes.ExpandRequest(**common, count=1), DB())
    await routes.deepen_node(routes.DeepenRequest(**common), DB())
    await routes.chat_node(routes.ChatRequest(**common, message="question"), DB())
    assert calls == [90, 120, 60]
