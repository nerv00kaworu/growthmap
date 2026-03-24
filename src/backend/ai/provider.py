"""AI Provider interface — pluggable LLM backend"""
import os
import json
import httpx
from typing import Optional

# Default to local proxy; override via env
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("GITHUB_TOKEN", ""))
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")


async def llm_complete(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """Send a chat completion request to any OpenAI-compatible API."""
    model = model or LLM_MODEL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
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

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

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
