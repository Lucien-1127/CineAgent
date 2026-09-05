"""Provider abstraction layer. Pipeline only sees these contracts; vendors live in adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """Base for all provider errors."""


class AuthError(ProviderError):
    """401: bad/missing credentials."""


class RateLimitError(ProviderError):
    """429: quota/rate limit. Includes retry-after hint if known."""


class ValidationError(ProviderError):
    """422: request payload was rejected by the API."""


class TimeoutError(ProviderError):
    """Request timed out."""


class ProviderFailure(ProviderError):
    """5xx: provider-side failure."""


class BudgetExceededError(ProviderError):
    """Estimated spend would exceed the project budget limit."""


class RemoteJobError(ProviderError):
    """A remote generation job failed or could not be resumed."""


def classify_http_status(status: int, body: str = "") -> ProviderError:
    """Maps an HTTP status to a typed provider error (no blanket except)."""
    if status == 401 or status == 403:
        return AuthError(f"auth failed ({status})")
    if status == 429:
        return RateLimitError(f"rate limited ({status})")
    if status == 422:
        return ValidationError(f"payload rejected ({status}): {body[:200]}")
    if status >= 500:
        return ProviderFailure(f"provider 5xx ({status})")
    return ProviderError(f"unhandled status {status}")


class TextProvider(ABC):
    """Abstract text/LLM provider. Structured outputs MUST be validated Pydantic."""

    name: str = "abstract"

    @abstractmethod
    async def chat(
        self, system: str, user: str, temperature: float = 0.7
    ) -> str:
        """Return raw text. Robust callers use structured() instead."""

    @abstractmethod
    async def structured(
        self, schema: Type[T], system: str, user: str,
        temperature: float = 0.7,
    ) -> T:
        """Ask the provider for a JSON object matching `schema` and validate it.

        Raises ValidationError (or ValueError) if parsing/validation fails —
        free-text is NEVER accepted as a fallback.
        """
        raise NotImplementedError


class ImageProvider(ABC):
    name: str = "abstract-image"


class VideoProvider(ABC):
    name: str = "abstract-video"


class AudioProvider(ABC):
    name: str = "abstract-audio"
