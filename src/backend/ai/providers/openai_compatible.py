"""OpenAI-compatible API provider."""
import os
import asyncio
import httpx
from typing import Optional

from .base import LLMProvider
from ai.diagnostics import LLMInvalidResponse


# Default values from environment
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
DEFAULT_API_KEY = os.getenv("GROWTHMAP_LLM_KEY_DEFAULT", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


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
    ) -> str:
        """Send a chat completion request to OpenAI-compatible API."""
        if not self.api_key:
            raise ValueError("API key is required for OpenAI-compatible provider")
        
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

        request_timeout = httpx.Timeout(30.0, connect=10.0)
        data: dict | list | None = None

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            for attempt in range(2):
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if resp.status_code in RETRYABLE_STATUS_CODES and attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    resp.raise_for_status()
                    try: data = resp.json()
                    except (ValueError,TypeError,AttributeError,KeyError) as exc: raise LLMInvalidResponse("invalid JSON") from exc
                    break
                except httpx.TimeoutException:
                    if attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    raise
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in RETRYABLE_STATUS_CODES and attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    raise

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
