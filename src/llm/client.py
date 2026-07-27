"""Public LLM facade: ``llm.generate(task=..., messages=...)``."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from src.llm.metrics import LLMMetrics
from src.llm.models import ChatMessage, LLMResponse
from src.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class LLM:
    """Provider-agnostic LLM client with task-based routing.

    Preferred public entry point::

        llm = LLM.from_config()
        response = llm.generate(task="research", messages=[...])
    """

    def __init__(self, router: LLMRouter) -> None:
        if router is None:
            raise ValueError("router is required")
        self._router = router

    @classmethod
    def from_config(
        cls,
        path: str | None = None,
        *,
        metrics: LLMMetrics | None = None,
    ) -> LLM:
        """Build an :class:`LLM` from router YAML."""
        return cls(LLMRouter.from_yaml(path, metrics=metrics))

    @property
    def router(self) -> LLMRouter:
        return self._router

    @property
    def metrics(self) -> LLMMetrics:
        return self._router.metrics

    def generate(
        self,
        task: str,
        messages: Sequence[ChatMessage] | Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> LLMResponse:
        """Generate a completion for ``task`` using the configured route.

        Args:
            task: Logical task name (``research``, ``director``, ``prompt``, …).
            messages: Chat messages (``ChatMessage`` or role/content mappings).
            temperature: Optional sampling override.
            max_tokens: Optional max-token override.
            response_format: Optional provider response format (e.g. JSON mode).
            model: Optional model override.
            provider: Optional provider override.

        Returns:
            Structured :class:`LLMResponse`.
        """
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        return self._router.generate(
            task=task.strip().lower(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            model=model,
            provider=provider,
        )


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    """Return a process-wide :class:`LLM` loaded from packaged router YAML."""
    logger.info("event=llm_singleton_init")
    return LLM.from_config()


def reset_llm_singleton() -> None:
    """Clear the cached :func:`get_llm` instance (tests / reconfigure)."""
    get_llm.cache_clear()
