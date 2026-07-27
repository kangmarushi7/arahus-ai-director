"""High-resolution wall-clock timer for pipeline stage profiling."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Timer:
    """Monotonic duration timer with UTC start/end timestamps.

    Uses :func:`time.perf_counter` for duration and wall-clock UTC for
    ``start_time`` / ``end_time`` so reports remain human-readable while
    durations stay accurate under clock adjustments.
    """

    start_time: datetime | None = None
    end_time: datetime | None = None
    _mono_start: float | None = None
    _mono_end: float | None = None

    def start(self) -> Timer:
        """Mark the start of a timed interval. Returns ``self`` for chaining."""
        if self._mono_start is not None and self._mono_end is None:
            raise RuntimeError("timer already running")
        self.start_time = utc_now()
        self.end_time = None
        self._mono_start = time.perf_counter()
        self._mono_end = None
        return self

    def stop(self) -> float:
        """Stop the timer and return elapsed milliseconds.

        Returns:
            Duration in milliseconds.

        Raises:
            RuntimeError: If the timer was never started or already stopped.
        """
        if self._mono_start is None:
            raise RuntimeError("timer has not been started")
        if self._mono_end is not None:
            raise RuntimeError("timer already stopped")
        self._mono_end = time.perf_counter()
        self.end_time = utc_now()
        return self.duration_ms

    @property
    def running(self) -> bool:
        """Whether the timer has been started and not yet stopped."""
        return self._mono_start is not None and self._mono_end is None

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds since start (live while running, final once stopped)."""
        if self._mono_start is None:
            return 0.0
        end = self._mono_end if self._mono_end is not None else time.perf_counter()
        return max(0.0, (end - self._mono_start) * 1000.0)

    @property
    def duration_ms(self) -> float:
        """Final duration in milliseconds.

        Raises:
            RuntimeError: If the timer has not been stopped yet.
        """
        if self._mono_start is None or self._mono_end is None:
            raise RuntimeError("timer has not been stopped")
        return max(0.0, (self._mono_end - self._mono_start) * 1000.0)

    @property
    def duration_seconds(self) -> float:
        """Final duration in seconds."""
        return self.duration_ms / 1000.0

    @classmethod
    def start_new(cls) -> Timer:
        """Create and immediately start a new timer."""
        return cls().start()


@contextmanager
def timed() -> Iterator[Timer]:
    """Context manager that starts a :class:`Timer` and stops it on exit.

    Yields:
        The running :class:`Timer`. After the block, ``duration_ms`` is set
        even if the block raised.
    """
    timer = Timer.start_new()
    try:
        yield timer
    finally:
        if timer.running:
            timer.stop()
