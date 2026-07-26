"""Reusable abstract base for every AI agent in the pipeline."""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


class BaseAgent(ABC, Generic[T]):
    """Provider-agnostic base class for pipeline agents.

    Subclasses implement :meth:`run` with their domain logic. Observability
    helpers (:meth:`_before_run`, :meth:`_after_run`, :meth:`_handle_error`)
    and :meth:`_execute` provide logging, retries, and timing without coupling
    this layer to any LLM or storage provider.
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        debug: bool | None = None,
    ) -> None:
        """Configure shared agent infrastructure.

        Args:
            max_retries: Maximum attempts for :meth:`_execute` (including the
                first try). Values below ``1`` are treated as ``1``.
            retry_backoff_seconds: Base delay between retries; multiplied by
                the attempt number (linear backoff).
            debug: When ``True``, emit verbose debug logs. Defaults to the
                ``AGENT_DEBUG`` environment flag when omitted.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.debug = _env_flag("AGENT_DEBUG") if debug is None else debug
        self.progress_callback: Callable[[str], None] | None = None

    def _log_progress(self, message: str) -> None:
        """Forward a human-readable step to the optional progress sink."""
        if self.progress_callback is not None:
            try:
                self.progress_callback(message)
            except Exception:  # noqa: BLE001 - UI sinks must not break agents
                self.logger.exception("progress_callback failed")
    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> T:
        """Execute the agent's core work and return a typed result.

        Subclasses must implement this method. Prefer wrapping the real work
        with :meth:`_execute` so retries, timing, and hooks apply uniformly.
        """

    def _before_run(self, *args: Any, **kwargs: Any) -> None:
        """Hook invoked once before the first attempt of :meth:`_execute`.

        Override to add pre-flight checks or context logging. The default
        implementation logs the call at INFO (or DEBUG when ``debug`` is on).
        """
        self.logger.info("%s starting", self.__class__.__name__)
        self._log_progress(f"{self.__class__.__name__}: starting")
        if self.debug:
            self.logger.debug(
                "%s _before_run args=%r kwargs=%r",
                self.__class__.__name__,
                args,
                kwargs,
            )

    def _after_run(
        self,
        result: T,
        elapsed_seconds: float,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Hook invoked after a successful :meth:`_execute`.

        Args:
            result: Value returned by the successful operation.
            elapsed_seconds: Wall-clock duration of all attempts combined.
            *args: Positional context forwarded from :meth:`_execute`.
            **kwargs: Keyword context forwarded from :meth:`_execute`.
        """
        self.logger.info(
            "%s completed in %.3fs",
            self.__class__.__name__,
            elapsed_seconds,
        )
        self._log_progress(
            f"{self.__class__.__name__}: finished in {elapsed_seconds:.1f}s"
        )
        if self.debug:
            self.logger.debug(
                "%s _after_run result_type=%s args=%r kwargs=%r",
                self.__class__.__name__,
                type(result).__name__,
                args,
                kwargs,
            )

    def _handle_error(
        self,
        error: Exception,
        attempt: int,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Hook invoked when an attempt inside :meth:`_execute` fails.

        Does not suppress the exception. Override to add metrics or alerts.

        Args:
            error: Exception raised by the failed attempt.
            attempt: 1-based attempt number that failed.
            *args: Positional context forwarded from :meth:`_execute`.
            **kwargs: Keyword context forwarded from :meth:`_execute`.
        """
        level = logging.WARNING if attempt < self.max_retries else logging.ERROR
        self.logger.log(
            level,
            "%s attempt %s/%s failed: %s",
            self.__class__.__name__,
            attempt,
            self.max_retries,
            error,
        )
        self._log_progress(
            f"{self.__class__.__name__}: attempt {attempt}/{self.max_retries} "
            f"failed — {type(error).__name__}: {error}"
        )
        if self.debug:
            self.logger.debug(
                "%s _handle_error args=%r kwargs=%r",
                self.__class__.__name__,
                args,
                kwargs,
                exc_info=error,
            )

    def _execute(
        self,
        operation: Callable[[], T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run ``operation`` with hooks, timing, and linear retry backoff.

        Args:
            operation: Zero-argument callable that performs the agent work and
                returns a value of type ``T``.
            *args: Optional context passed to lifecycle hooks (not to
                ``operation``).
            **kwargs: Optional context passed to lifecycle hooks (not to
                ``operation``).

        Returns:
            The successful result of ``operation``.

        Raises:
            Exception: Re-raises the last error after all retries are exhausted.
        """
        self._before_run(*args, **kwargs)
        started = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            self._log_progress(
                f"{self.__class__.__name__}: attempt {attempt}/{self.max_retries}"
            )
            try:
                result = operation()
            except Exception as error:  # noqa: BLE001 - retry policy is deliberate
                last_error = error
                self._handle_error(error, attempt, *args, **kwargs)
                if attempt >= self.max_retries:
                    break
                delay = self.retry_backoff_seconds * attempt
                if delay > 0:
                    self.logger.info(
                        "%s retrying in %.2fs",
                        self.__class__.__name__,
                        delay,
                    )
                    self._log_progress(
                        f"{self.__class__.__name__}: retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                continue

            elapsed = time.perf_counter() - started
            self._after_run(result, elapsed, *args, **kwargs)
            return result

        assert last_error is not None  # noqa: S101 - loop always assigns on failure
        raise last_error
