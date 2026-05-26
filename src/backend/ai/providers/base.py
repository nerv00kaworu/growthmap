"""LLM Provider base types and protocol."""
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel


class LLMConfig(BaseModel):
    """Configuration for LLM provider."""
    provider: str  # mock, openai_compatible, custom, openai
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class LLMResult(BaseModel):
    """Result from LLM call."""
    content: str
    model: Optional[str] = None
    provider: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        ...

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """Make a chat completion call."""
        ...