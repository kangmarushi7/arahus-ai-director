"""LLM router exceptions."""

from __future__ import annotations


class LLMError(Exception):
    """Base error for the LLM router stack."""


class LLMConfigError(LLMError):
    """Raised when router YAML / runtime config is invalid."""


class LLMProviderError(LLMError):
    """Raised when a provider request fails (possibly after retries)."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.retriable = retriable


class LLMTimeoutError(LLMProviderError):
    """Raised when a provider call times out."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            model=model,
            status_code=None,
            retriable=True,
        )


class LLMRateLimitError(LLMProviderError):
    """Raised on HTTP 429 / provider rate limiting."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            model=model,
            status_code=429,
            retriable=True,
        )


class LLMRoutingError(LLMError):
    """Raised when a task cannot be routed to a provider/model."""
