"""In-memory metrics collection for the AI Director pipeline.

Tracks latency for LLM, RunPod, and R2 calls, token usage and estimated cost,
image counts, and overall pipeline duration. Everything is kept in process
memory and can be exported as JSON.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

# Metric names for the three timed external dependencies.
LLM_LATENCY = "llm_latency"
RUNPOD_LATENCY = "runpod_latency"
R2_UPLOAD_LATENCY = "r2_upload_latency"
PIPELINE_DURATION = "pipeline_duration"

_LATENCY_METRICS = (
    LLM_LATENCY,
    RUNPOD_LATENCY,
    R2_UPLOAD_LATENCY,
    PIPELINE_DURATION,
)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LatencySeries:
    """Aggregated timing samples for one operation, in seconds."""

    count: int = 0
    total_seconds: float = 0.0
    min_seconds: float | None = None
    max_seconds: float | None = None
    samples: list[float] = field(default_factory=list)

    def record(self, seconds: float) -> None:
        """Add one duration sample."""
        self.count += 1
        self.total_seconds += seconds
        self.min_seconds = (
            seconds if self.min_seconds is None else min(self.min_seconds, seconds)
        )
        self.max_seconds = (
            seconds if self.max_seconds is None else max(self.max_seconds, seconds)
        )
        self.samples.append(seconds)

    @property
    def average_seconds(self) -> float:
        """Mean duration, or ``0.0`` when no samples exist."""
        return self.total_seconds / self.count if self.count else 0.0

    def to_dict(self, *, include_samples: bool = False) -> dict[str, Any]:
        """Serialize the series into a JSON-friendly dictionary."""
        payload: dict[str, Any] = {
            "count": self.count,
            "total_seconds": round(self.total_seconds, 6),
            "average_seconds": round(self.average_seconds, 6),
            "min_seconds": (
                round(self.min_seconds, 6) if self.min_seconds is not None else None
            ),
            "max_seconds": (
                round(self.max_seconds, 6) if self.max_seconds is not None else None
            ),
        }
        if include_samples:
            payload["samples"] = [round(sample, 6) for sample in self.samples]
        return payload


class MetricsCollector:
    """Thread-safe, in-memory collector for pipeline metrics."""

    def __init__(self) -> None:
        """Initialize empty counters and latency series."""
        self._lock = threading.RLock()
        self._started_at = _utc_now_iso()
        self._latencies: dict[str, LatencySeries] = {
            name: LatencySeries() for name in _LATENCY_METRICS
        }
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._estimated_cost = 0.0
        self._images_generated = 0

    # Latency recording ---------------------------------------------------

    def record_llm_latency(self, seconds: float) -> None:
        """Record one LLM request duration in seconds."""
        self._record_latency(LLM_LATENCY, seconds)

    def record_runpod_latency(self, seconds: float) -> None:
        """Record one RunPod request duration in seconds."""
        self._record_latency(RUNPOD_LATENCY, seconds)

    def record_r2_upload_latency(self, seconds: float) -> None:
        """Record one R2 upload duration in seconds."""
        self._record_latency(R2_UPLOAD_LATENCY, seconds)

    def record_pipeline_duration(self, seconds: float) -> None:
        """Record one end-to-end pipeline run duration in seconds."""
        self._record_latency(PIPELINE_DURATION, seconds)

    def _record_latency(self, metric: str, seconds: float) -> None:
        """Append a duration sample to ``metric``."""
        if seconds < 0:
            raise ValueError("latency must be non-negative")
        with self._lock:
            self._latencies[metric].record(float(seconds))

    @contextmanager
    def measure(self, metric: str) -> Iterator[None]:
        """Time a block of code and record it under ``metric``.

        Args:
            metric: One of the module-level latency metric names.

        Yields:
            ``None`` while the timed block executes.
        """
        if metric not in _LATENCY_METRICS:
            raise ValueError(f"unknown latency metric: {metric}")
        started = time.perf_counter()
        try:
            yield
        finally:
            self._record_latency(metric, time.perf_counter() - started)

    # Counters ------------------------------------------------------------

    def record_tokens(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Add prompt and completion token counts."""
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("token counts must be non-negative")
        with self._lock:
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens

    def record_cost(self, amount: float) -> None:
        """Add an estimated cost amount, in provider currency units."""
        if amount < 0:
            raise ValueError("cost must be non-negative")
        with self._lock:
            self._estimated_cost += float(amount)

    def record_images_generated(self, count: int = 1) -> None:
        """Increase the number of generated images."""
        if count < 0:
            raise ValueError("image count must be non-negative")
        with self._lock:
            self._images_generated += count

    # Accessors -----------------------------------------------------------

    @property
    def prompt_tokens(self) -> int:
        """Total prompt tokens recorded."""
        with self._lock:
            return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        """Total completion tokens recorded."""
        with self._lock:
            return self._completion_tokens

    @property
    def estimated_cost(self) -> float:
        """Total estimated cost recorded."""
        with self._lock:
            return self._estimated_cost

    @property
    def images_generated(self) -> int:
        """Total images generated."""
        with self._lock:
            return self._images_generated

    def snapshot(self, *, include_samples: bool = False) -> dict[str, Any]:
        """Return all metrics as a JSON-serializable dictionary.

        Args:
            include_samples: When ``True``, include every raw latency sample.

        Returns:
            A dictionary with latency, token, cost, and image metrics.
        """
        with self._lock:
            return {
                "started_at": self._started_at,
                "exported_at": _utc_now_iso(),
                "latency": {
                    name: series.to_dict(include_samples=include_samples)
                    for name, series in self._latencies.items()
                },
                "tokens": {
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": self._completion_tokens,
                    "total_tokens": self._prompt_tokens + self._completion_tokens,
                },
                "estimated_cost": round(self._estimated_cost, 6),
                "images_generated": self._images_generated,
            }

    def to_json(
        self,
        *,
        include_samples: bool = False,
        indent: int | None = 2,
    ) -> str:
        """Export all metrics as a JSON string."""
        return json.dumps(
            self.snapshot(include_samples=include_samples),
            indent=indent,
            ensure_ascii=False,
        )

    def reset(self) -> None:
        """Clear every counter and latency series."""
        with self._lock:
            self._started_at = _utc_now_iso()
            self._latencies = {name: LatencySeries() for name in _LATENCY_METRICS}
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._estimated_cost = 0.0
            self._images_generated = 0
