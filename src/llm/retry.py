"""Retry helpers for transient LLM provider failures."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from src.llm.exceptions import LLMProviderError, LLMRateLimitError, LLMTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff policy for provider calls."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")

    def delay_for_attempt(self, attempt: int) -> float:
        """Return sleep seconds before the next try (``attempt`` is 1-based)."""
        expo = self.base_delay_seconds * (2 ** max(0, attempt - 1))
        delay = min(self.max_delay_seconds, expo)
        if self.jitter_ratio <= 0:
            return delay
        jitter = delay * self.jitter_ratio * random.random()
        return min(self.max_delay_seconds, delay + jitter)


def is_retriable(exc: BaseException) -> bool:
    """Return whether ``exc`` should be retried."""
    if isinstance(exc, (LLMRateLimitError, LLMTimeoutError)):
        return True
    if isinstance(exc, LLMProviderError):
        if exc.retriable:
            return True
        if exc.status_code == 429:
            return True
        if exc.status_code is not None and exc.status_code >= 500:
            return True
    return False


@dataclass
class RetryState:
    """Mutable retry counter shared with callers (e.g. cost tracking)."""

    retries: int = 0


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    operation_name: str = "llm_request",
    state: RetryState | None = None,
) -> T:
    """Execute ``operation`` with retry/backoff on transient failures.

    When ``state`` is provided, ``state.retries`` is set to the number of
    failed attempts that occurred before the final outcome (0 on first-try
    success).
    """
    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = operation()
            if state is not None:
                state.retries = attempt - 1
            return result
        except Exception as exc:  # noqa: BLE001 - classify then re-raise
            last_error = exc
            if state is not None:
                state.retries = attempt - 1
            if attempt >= policy.max_attempts or not is_retriable(exc):
                raise
            sleep_for = policy.delay_for_attempt(attempt)
            logger.warning(
                "event=llm_retry operation=%s attempt=%s/%s sleep=%.3f error=%s",
                operation_name,
                attempt,
                policy.max_attempts,
                sleep_for,
                exc,
            )
            time.sleep(sleep_for)

    assert last_error is not None
    raise last_error
