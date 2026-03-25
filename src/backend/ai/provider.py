"""AI Provider interface — pluggable LLM backend"""
import asyncio
import os
import json
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Default to local proxy; override via env
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("GITHUB_TOKEN", ""))
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def get_provider_config() -> tuple[str, str, str]:
    base_url = LLM_BASE_URL.strip()
    api_key = LLM_API_KEY.strip()
    model = LLM_MODEL.strip()

    if not base_url:
        raise ValueError("LLM_BASE_URL is required before calling the AI provider")
    if not api_key:
        raise ValueError("LLM_API_KEY or GITHUB_TOKEN is required before calling the AI provider")
    if not model:
        raise ValueError("LLM_MODEL is required before calling the AI provider")

    return base_url.rstrip("/"), api_key, model


async def llm_complete(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """Send a chat completion request to any OpenAI-compatible API."""
    base_url, api_key, default_model = get_provider_config()
    model = (model or default_model).strip()
    if not model:
        raise ValueError("LLM model cannot be blank")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
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

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=request_timeout,
                )
                status_code = getattr(resp, "status_code", 200)
                if status_code in RETRYABLE_STATUS_CODES and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                resp.raise_for_status()
                data = resp.json()
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

    if data is None:
        raise RuntimeError("LLM request did not produce a response payload")

    # Handle both OpenAI and Kimi-style responses
    if "choices" in data and data["choices"]:
        return data["choices"][0]["message"]["content"]
    elif "content" in data:
        return data["content"]
    else:
        raise ValueError(f"Unexpected LLM response format: {list(data.keys())}")


def parse_json_response(text: str) -> list | dict:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    text = text.strip()
    # Strip ```json ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)
