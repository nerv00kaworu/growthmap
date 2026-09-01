"""OpenAI-compatible API provider."""
import math
import os
import httpx
from typing import Optional

from .base import LLMProvider
from ai.diagnostics import LLMInvalidResponse


# Default values from environment
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
DEFAULT_API_KEY = os.getenv("GROWTHMAP_LLM_KEY_DEFAULT", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 60.0
CONNECT_TIMEOUT_SECONDS = 10.0


class OpenAICompatibleProvider(LLMProvider):
    """Minimal async HTTP client for OpenAI-compatible /chat/completions."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or DEFAULT_API_KEY
        self.default_model = default_model or DEFAULT_MODEL

    @property
    def name(self) -> str:
        return "openai_compatible"

    async def complete(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    ) -> str:
        """Send exactly one chat completion request.

        ``response_timeout_seconds`` bounds response/read time. A dispatched
        completion is never retried because the upstream may have generated a
        billable response even when GrowthMap did not receive it.
        """
        if not self.api_key:
            raise ValueError("API key is required for OpenAI-compatible provider")
        if (
            isinstance(response_timeout_seconds, bool)
            or not isinstance(response_timeout_seconds, (int, float))
            or response_timeout_seconds <= 0
            or response_timeout_seconds > 120
            or not math.isfinite(response_timeout_seconds)
        ):
            raise ValueError("Response timeout must be a finite number in (0, 120]")

        model = (model or self.default_model).strip()
        if not model:
            raise ValueError("Model cannot be blank")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        request_timeout = httpx.Timeout(
            response_timeout_seconds,
            connect=CONNECT_TIMEOUT_SECONDS,
        )

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            try: data = resp.json()
            except (ValueError,TypeError,AttributeError,KeyError) as exc: raise LLMInvalidResponse("invalid JSON") from exc

        if not isinstance(data, dict):
            raise LLMInvalidResponse("response container")
        try:
            if set(data) >= {"choices"}:
                choices=data["choices"]
                if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict): raise LLMInvalidResponse("choices")
                message=choices[0].get("message")
                if not isinstance(message,dict) or set(message) < {"content"}: raise LLMInvalidResponse("message")
                content=message["content"]
            elif set(data) >= {"content"}: content=data["content"]
            else: raise LLMInvalidResponse("shape")
            if not isinstance(content,str) or not content.strip() or len(content)>262144: raise LLMInvalidResponse("content")
            return content
        except LLMInvalidResponse: raise
        except (KeyError,TypeError,AttributeError,ValueError) as exc: raise LLMInvalidResponse("extraction") from exc
