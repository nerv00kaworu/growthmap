"""Process-memory-only provider secrets for desktop mode."""
import os
from fastapi import HTTPException

_secrets: dict[str, str] = {}

def put(provider_id: str, secret: str) -> None:
    if not secret or "\x00" in secret:
        raise HTTPException(400, "API key is required")
    _secrets[provider_id] = secret

def delete(provider_id: str) -> None:
    _secrets.pop(provider_id, None)

def get(provider_id: str) -> str | None:
    return _secrets.get(provider_id)

def desktop_mode() -> bool:
    return os.getenv("GROWTHMAP_DESKTOP_MODE") == "1"
