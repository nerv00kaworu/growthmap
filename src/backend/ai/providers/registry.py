"""LLM Provider registry — selects provider based on config."""
from typing import Optional
from .base import LLMProvider, LLMConfig
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider


# Singleton instances
_mock_provider: Optional[MockProvider] = None
_openai_provider: Optional[OpenAICompatibleProvider] = None


def get_provider(config: LLMConfig) -> LLMProvider:
    """Choose and return the appropriate LLM provider based on config.
    
    Supported providers:
    - "mock": Deterministic mock, no API key required
    - "openai_compatible": OpenAI-compatible HTTP API
    - "custom": Alias for openai_compatible (uses base_url/api_key/model)
    - "openai": Backwards compat — uses openai_compatible with base_url/api_key/model if provided
    """
    global _mock_provider, _openai_provider
    
    provider_val = config.provider.lower()
    
    if provider_val == "mock":
        if _mock_provider is None:
            _mock_provider = MockProvider()
        return _mock_provider
    
    if provider_val in ("openai_compatible", "custom", "openai"):
        # Check if overrides are provided
        base_url = config.base_url
        api_key = config.api_key
        model = config.model
        
        # For backwards compat: if provider is "openai" but no base_url, fall back to default
        if provider_val == "openai" and not base_url:
            base_url = None
            model = model or "gpt-4o"
        
        return OpenAICompatibleProvider(
            base_url=base_url,
            api_key=api_key,
            default_model=model,
        )
    
    # Default to openai_compatible with env defaults
    return OpenAICompatibleProvider()


async def test_connection(config: LLMConfig) -> dict:
    """Test if a provider configuration is valid.
    
    Returns dict with ok, provider, model, message.
    Does not expose API keys in the response.
    """
    try:
        provider = get_provider(config)
        
        # Get the resolved model name
        model = config.model or "default"
        
        # For mock, just verify it's instantiable
        if config.provider == "mock":
            return {
                "ok": True,
                "provider": config.provider,
                "model": model,
                "message": "Mock provider ready",
            }
        
        # For real providers, try a simple completion in the current async loop.
        result = await provider.complete(
            system="你是助理。",
            user="回覆「OK」一字。",
            max_tokens=10,
        )
        
        return {
            "ok": True,
            "provider": config.provider,
            "model": model,
            "message": f"連線成功：{result.strip()[:50]}",
        }
    except Exception as e:
        return {
            "ok": False,
            "provider": config.provider or "unknown",
            "model": config.model or "",
            "message": f"連線失敗：{str(e)}",
        }
