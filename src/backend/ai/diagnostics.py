"""Safe, stable diagnostics for LLM operations."""
from dataclasses import dataclass
import httpx

@dataclass(frozen=True)
class AIDiagnostic:
    status: int
    code: str
    message: str
    source_status: int | None = None

class LLMConfigurationError(Exception): pass
class LLMInvalidResponse(Exception): pass
class LLMProfileChanged(Exception): pass
class LLMSelectionChanged(Exception): pass

SAFE_MESSAGES = {
    "LLM_TIMEOUT": "The AI provider did not respond within the maximum wait. Please retry.",
    "LLM_AUTH_FAILED": "The AI provider rejected its credentials. Check the selected provider configuration.",
    "LLM_RATE_LIMITED": "The AI provider rate limit was reached. Wait and retry.",
    "LLM_UPSTREAM_ERROR": "The AI provider is temporarily unavailable. Please retry.",
    "LLM_INVALID_RESPONSE": "The AI provider returned a response GrowthMap could not validate.",
    "LLM_SELECTION_CHANGED": "The selected AI provider changed. Reload and retry.",
    "LLM_PROFILE_CHANGED": "The selected AI profile changed. Review it and retry.",
    "LLM_CONFIGURATION_ERROR": "The selected AI provider is unavailable; rebind it in secure storage.",
}

def classify_ai_exception(exc: Exception) -> AIDiagnostic:
    if isinstance(exc, LLMSelectionChanged): code, status = "LLM_SELECTION_CHANGED", 409
    elif isinstance(exc, LLMProfileChanged): code, status = "LLM_PROFILE_CHANGED", 409
    elif isinstance(exc, LLMInvalidResponse): code, status = "LLM_INVALID_RESPONSE", 502
    elif isinstance(exc, LLMConfigurationError): code, status = "LLM_CONFIGURATION_ERROR", 400
    elif isinstance(exc, httpx.TimeoutException): code, status = "LLM_TIMEOUT", 504
    elif isinstance(exc, httpx.HTTPStatusError):
        source = exc.response.status_code
        if source in (401, 403): code, status = "LLM_AUTH_FAILED", 401
        elif source == 429: code, status = "LLM_RATE_LIMITED", 429
        else: code, status = "LLM_UPSTREAM_ERROR", 502
        return AIDiagnostic(status, code, SAFE_MESSAGES[code], source)
    elif isinstance(exc, (httpx.NetworkError, httpx.RequestError, ConnectionError, OSError)): code, status = "LLM_UPSTREAM_ERROR", 502
    else: code, status = "LLM_UPSTREAM_ERROR", 502
    return AIDiagnostic(status, code, SAFE_MESSAGES[code])
