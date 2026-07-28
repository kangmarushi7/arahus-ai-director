"""In-memory metrics for video generations."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from src.video.models import VideoGenerationMetrics


@dataclass
class _Bucket:
    requests: int = 0
    failures: int = 0
    runtime_ms_total: float = 0.0
    gpu_seconds_total: float = 0.0
    estimated_cost_total: float = 0.0
    duration_total: float = 0.0


@dataclass
class VideoMetrics:
    """Thread-safe counters for video engine traffic."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _by_provider: dict[str, _Bucket] = field(default_factory=dict)
    _by_model: dict[str, _Bucket] = field(default_factory=dict)
    _records: list[VideoGenerationMetrics] = field(default_factory=list)

    def record(self, metrics: VideoGenerationMetrics) -> None:
        """Record one generation attempt."""
        with self._lock:
            self._records.append(metrics)
            self._update(self._by_provider, metrics.provider, metrics)
            self._update(self._by_model, metrics.model, metrics)

    @property
    def records(self) -> list[VideoGenerationMetrics]:
        with self._lock:
            return list(self._records)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable metrics snapshot."""
        with self._lock:
            return {
                "by_provider": {
                    key: self._bucket_dict(bucket)
                    for key, bucket in self._by_provider.items()
                },
                "by_model": {
                    key: self._bucket_dict(bucket)
                    for key, bucket in self._by_model.items()
                },
                "total_requests": sum(b.requests for b in self._by_provider.values()),
                "total_failures": sum(b.failures for b in self._by_provider.values()),
                "total_estimated_cost": round(
                    sum(b.estimated_cost_total for b in self._by_provider.values()),
                    8,
                ),
                "total_gpu_seconds": round(
                    sum(b.gpu_seconds_total for b in self._by_provider.values()),
                    3,
                ),
                "recent": [item.to_dict() for item in self._records[-20:]],
            }

    def reset(self) -> None:
        with self._lock:
            self._by_provider.clear()
            self._by_model.clear()
            self._records.clear()

    @staticmethod
    def _update(
        bucket_map: dict[str, _Bucket],
        key: str,
        metrics: VideoGenerationMetrics,
    ) -> None:
        bucket = bucket_map.setdefault(key, _Bucket())
        bucket.requests += 1
        if not metrics.success:
            bucket.failures += 1
        bucket.runtime_ms_total += metrics.runtime_ms
        bucket.gpu_seconds_total += metrics.gpu_seconds
        bucket.estimated_cost_total += metrics.estimated_cost
        bucket.duration_total += metrics.duration

    @staticmethod
    def _bucket_dict(bucket: _Bucket) -> dict[str, float | int]:
        avg = bucket.runtime_ms_total / bucket.requests if bucket.requests else 0.0
        return {
            "requests": bucket.requests,
            "failures": bucket.failures,
            "runtime_ms_total": round(bucket.runtime_ms_total, 3),
            "runtime_ms_average": round(avg, 3),
            "gpu_seconds_total": round(bucket.gpu_seconds_total, 3),
            "duration_total": round(bucket.duration_total, 3),
            "estimated_cost_total": round(bucket.estimated_cost_total, 8),
        }
