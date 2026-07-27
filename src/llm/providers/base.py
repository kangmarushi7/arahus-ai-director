"""Provider protocol for LLM backends."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from src.llm.models import ChatMessage, ProviderCompletion


@runtime_checkable
class LLMProvider(Protocol):
    """Provider-agnostic chat completion interface."""

    @property
    def name(self) -> str:
        """Stable provider identifier (e.g. ``openrouter``)."""

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        temperature: float,
        max_tokens: int,
        response_format: Mapping[str, Any] | None = None,
    ) -> ProviderCompletion:
        """Execute one chat completion and return a structured completion."""
