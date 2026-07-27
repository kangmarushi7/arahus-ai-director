"""In-memory metrics for LLM router requests."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from src.llm.models import LLMResponse


@dataclass
class _TaskStats:
    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms_total: float = 0.0
    estimated_cost_total: float = 0.0


@dataclass
class LLMMetrics:
    """Thread-safe counters for LLM traffic."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _by_task: dict[str, _TaskStats] = field(default_factory=dict)
    _by_model: dict[str, _TaskStats] = field(default_factory=dict)

    def record(self, response: LLMResponse, *, failed: bool = False) -> None:
        """Record a successful or failed request."""
        task = response.task or "unknown"
        model = response.model or "unknown"
        with self._lock:
            self._update(self._by_task, task, response, failed=failed)
            self._update(self._by_model, model, response, failed=failed)

    def record_failure(
        self,
        *,
        task: str,
        model: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a hard failure without a full :class:`LLMResponse`."""
        synthetic = LLMResponse(
            text="",
            provider="unknown",
            model=model,
            latency_ms=latency_ms,
            task=task,
        )
        self.record(synthetic, failed=True)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable metrics snapshot."""
        with self._lock:
            return {
                "by_task": {
                    key: self._stats_dict(stats) for key, stats in self._by_task.items()
                },
                "by_model": {
                    key: self._stats_dict(stats) for key, stats in self._by_model.items()
                },
            }

    def reset(self) -> None:
        """Clear all counters."""
        with self._lock:
            self._by_task.clear()
            self._by_model.clear()

    @staticmethod
    def _update(
        bucket: dict[str, _TaskStats],
        key: str,
        response: LLMResponse,
        *,
        failed: bool,
    ) -> None:
        stats = bucket.setdefault(key, _TaskStats())
        stats.requests += 1
        if failed:
            stats.failures += 1
        stats.input_tokens += response.input_tokens
        stats.output_tokens += response.output_tokens
        stats.latency_ms_total += response.latency_ms
        stats.estimated_cost_total += response.estimated_cost

    @staticmethod
    def _stats_dict(stats: _TaskStats) -> dict[str, float | int]:
        avg_latency = (
            stats.latency_ms_total / stats.requests if stats.requests else 0.0
        )
        return {
            "requests": stats.requests,
            "failures": stats.failures,
            "input_tokens": stats.input_tokens,
            "output_tokens": stats.output_tokens,
            "latency_ms_total": round(stats.latency_ms_total, 3),
            "latency_ms_average": round(avg_latency, 3),
            "estimated_cost_total": round(stats.estimated_cost_total, 8),
        }
