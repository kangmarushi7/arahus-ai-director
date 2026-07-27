"""In-memory metrics collection and pipeline stage reports.

Tracks stage latencies, token usage, estimated cost, image counts, and retries.
Everything is kept in process memory and can be exported as JSON.

Also defines per-run :class:`StageMetrics` / :class:`PipelineMetrics` reports
used by :class:`~src.monitoring.profiler.PipelineProfiler`.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Stage and dependency latency metric names.
DOMAIN_LATENCY = "domain_latency"
RESEARCH_LATENCY = "research_latency"
DIRECTOR_LATENCY = "director_latency"
PROMPT_LATENCY = "prompt_latency"
PROMPT_COMPOSER_LATENCY = "prompt_composer_latency"
REVIEW_LATENCY = "review_latency"
RUNPOD_LATENCY = "runpod_latency"
RUNPOD_SUBMIT_LATENCY = "runpod_submit_latency"
RUNPOD_POLL_LATENCY = "runpod_poll_latency"
CLOUDFLARE_UPLOAD_LATENCY = "cloudflare_upload_latency"
DATABASE_LATENCY = "database_latency"
TOTAL_LATENCY = "total_latency"

# Backward-compatible aliases used by earlier pipeline/dashboard code.
R2_UPLOAD_LATENCY = CLOUDFLARE_UPLOAD_LATENCY
PIPELINE_DURATION = TOTAL_LATENCY
LLM_LATENCY = "llm_latency"

_LATENCY_METRICS = (
    DOMAIN_LATENCY,
    RESEARCH_LATENCY,
    DIRECTOR_LATENCY,
    PROMPT_LATENCY,
    PROMPT_COMPOSER_LATENCY,
    REVIEW_LATENCY,
    RUNPOD_LATENCY,
    RUNPOD_SUBMIT_LATENCY,
    RUNPOD_POLL_LATENCY,
    CLOUDFLARE_UPLOAD_LATENCY,
    DATABASE_LATENCY,
    TOTAL_LATENCY,
    LLM_LATENCY,
)

# Canonical stage display names for the profiler report.
STAGE_DOMAIN_DETECTION = "Domain Detection"
STAGE_RESEARCH = "Research"
STAGE_DIRECTOR = "Director"
STAGE_PROMPT = "Prompt"
STAGE_REVIEW = "Review"
STAGE_PROMPT_COMPOSER = "Prompt Composer"
STAGE_RUNPOD_SUBMIT = "RunPod submission"
STAGE_RUNPOD_POLL = "RunPod polling"
STAGE_CLOUDFLARE_UPLOAD = "Cloudflare upload"
STAGE_DATABASE = "Database persistence"

# Shorter labels used in the console table (match operator expectations).
_TABLE_LABELS: dict[str, str] = {
    STAGE_DOMAIN_DETECTION: "Domain Detection",
    STAGE_RESEARCH: "Research",
    STAGE_DIRECTOR: "Director",
    STAGE_PROMPT: "Prompt",
    STAGE_REVIEW: "Review",
    STAGE_PROMPT_COMPOSER: "Prompt Composer",
    STAGE_RUNPOD_SUBMIT: "RunPod submission",
    STAGE_RUNPOD_POLL: "RunPod polling",
    STAGE_CLOUDFLARE_UPLOAD: "Upload",
    STAGE_DATABASE: "Database",
}

# Preferred row order for the console table.
STAGE_TABLE_ORDER: tuple[str, ...] = (
    STAGE_DOMAIN_DETECTION,
    STAGE_RESEARCH,
    STAGE_DIRECTOR,
    STAGE_PROMPT,
    STAGE_PROMPT_COMPOSER,
    STAGE_REVIEW,
    STAGE_RUNPOD_SUBMIT,
    STAGE_RUNPOD_POLL,
    STAGE_CLOUDFLARE_UPLOAD,
    STAGE_DATABASE,
)

# Map profiler stage names → MetricsCollector latency keys.
STAGE_TO_METRIC: dict[str, str] = {
    STAGE_DOMAIN_DETECTION: DOMAIN_LATENCY,
    STAGE_RESEARCH: RESEARCH_LATENCY,
    STAGE_DIRECTOR: DIRECTOR_LATENCY,
    STAGE_PROMPT: PROMPT_LATENCY,
    STAGE_PROMPT_COMPOSER: PROMPT_COMPOSER_LATENCY,
    STAGE_REVIEW: REVIEW_LATENCY,
    STAGE_RUNPOD_SUBMIT: RUNPOD_SUBMIT_LATENCY,
    STAGE_RUNPOD_POLL: RUNPOD_POLL_LATENCY,
    STAGE_CLOUDFLARE_UPLOAD: CLOUDFLARE_UPLOAD_LATENCY,
    STAGE_DATABASE: DATABASE_LATENCY,
}


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def format_duration_ms(duration_ms: float) -> str:
    """Format a millisecond duration for console display.

    Values under one second use whole milliseconds (``320 ms``).
    Values of one second or more use one decimal place (``41.2 s``).
    """
    ms = max(0.0, float(duration_ms))
    if ms < 1000.0:
        return f"{ms:.0f} ms"
    return f"{ms / 1000.0:.1f} s"


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


@dataclass(slots=True)
class StageMetrics:
    """Timing and outcome for a single pipeline stage invocation."""

    stage: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "stage": self.stage,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": round(self.duration_ms, 3),
            "success": self.success,
            "error": self.error,
        }


@dataclass(slots=True)
class StageSummary:
    """Aggregated view of one or more samples for the same stage name."""

    stage: str
    count: int
    duration_ms: float
    success: bool
    error: str | None = None

    @property
    def label(self) -> str:
        """Console table label, with a count suffix when sampled more than once."""
        base = _TABLE_LABELS.get(self.stage, self.stage)
        if self.count > 1:
            return f"{base} (x{self.count})"
        return base


@dataclass(slots=True)
class PipelineMetrics:
    """Final per-run profiling report for one pipeline execution."""

    stages: list[StageMetrics] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    topic: str | None = None

    def add_stage(self, stage: StageMetrics) -> None:
        """Append a stage sample."""
        self.stages.append(stage)
        if not stage.success:
            self.success = False
            if self.error is None:
                self.error = stage.error

    def summarize_stages(self) -> list[StageSummary]:
        """Collapse samples by stage name in preferred table order."""
        buckets: dict[str, list[StageMetrics]] = {}
        for sample in self.stages:
            buckets.setdefault(sample.stage, []).append(sample)

        ordered_names = [name for name in STAGE_TABLE_ORDER if name in buckets]
        ordered_names.extend(
            name for name in buckets if name not in STAGE_TABLE_ORDER
        )

        summaries: list[StageSummary] = []
        for name in ordered_names:
            samples = buckets[name]
            errors = [s.error for s in samples if s.error]
            summaries.append(
                StageSummary(
                    stage=name,
                    count=len(samples),
                    duration_ms=sum(s.duration_ms for s in samples),
                    success=all(s.success for s in samples),
                    error=errors[0] if errors else None,
                )
            )
        return summaries

    def format_table(self) -> str:
        """Render a pretty console table of stage durations.

        Example::

            Stage                     Duration
            -----------------------------------
            Domain Detection          320 ms
            Research                  41.2 s
            ...
            -----------------------------------
            Total                    144.9 s
        """
        summaries = self.summarize_stages()
        rows: list[tuple[str, str]] = [
            (summary.label, format_duration_ms(summary.duration_ms))
            for summary in summaries
        ]
        rows.append(("Total", format_duration_ms(self.total_duration_ms)))

        name_width = max(len("Stage"), *(len(name) for name, _ in rows))
        duration_width = max(len("Duration"), *(len(dur) for _, dur in rows))
        rule = "-" * (name_width + duration_width + 2)

        lines = [
            f"{'Stage':<{name_width}}  {'Duration':>{duration_width}}",
            rule,
        ]
        success_by_label = {item.label: item.success for item in summaries}
        for name, duration in rows[:-1]:
            marker = "" if success_by_label.get(name, True) else "  FAIL"
            lines.append(
                f"{name:<{name_width}}  {duration:>{duration_width}}{marker}"
            )
        lines.append(rule)
        total_name, total_dur = rows[-1]
        lines.append(f"{total_name:<{name_width}}  {total_dur:>{duration_width}}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full report to a JSON-friendly dictionary."""
        return {
            "topic": self.topic,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
            "total_duration_ms": round(self.total_duration_ms, 3),
            "success": self.success,
            "error": self.error,
            "stages": [stage.to_dict() for stage in self.stages],
            "summary": [
                {
                    "stage": item.stage,
                    "label": item.label,
                    "count": item.count,
                    "duration_ms": round(item.duration_ms, 3),
                    "success": item.success,
                    "error": item.error,
                }
                for item in self.summarize_stages()
            ],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Export the report as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


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
        self._retry_count = 0

    # Latency recording ---------------------------------------------------

    def record_domain_latency(self, seconds: float) -> None:
        """Record domain-detection latency in seconds."""
        self._record_latency(DOMAIN_LATENCY, seconds)

    def record_research_latency(self, seconds: float) -> None:
        """Record research-agent latency in seconds."""
        self._record_latency(RESEARCH_LATENCY, seconds)

    def record_director_latency(self, seconds: float) -> None:
        """Record director-agent latency in seconds."""
        self._record_latency(DIRECTOR_LATENCY, seconds)

    def record_prompt_latency(self, seconds: float) -> None:
        """Record prompt-agent latency in seconds."""
        self._record_latency(PROMPT_LATENCY, seconds)

    def record_prompt_composer_latency(self, seconds: float) -> None:
        """Record prompt-composer latency in seconds."""
        self._record_latency(PROMPT_COMPOSER_LATENCY, seconds)

    def record_review_latency(self, seconds: float) -> None:
        """Record review-agent latency in seconds."""
        self._record_latency(REVIEW_LATENCY, seconds)

    def record_runpod_latency(self, seconds: float) -> None:
        """Record RunPod image-generation latency in seconds."""
        self._record_latency(RUNPOD_LATENCY, seconds)

    def record_runpod_submit_latency(self, seconds: float) -> None:
        """Record RunPod job-submit latency in seconds."""
        self._record_latency(RUNPOD_SUBMIT_LATENCY, seconds)

    def record_runpod_poll_latency(self, seconds: float) -> None:
        """Record RunPod poll-wait latency in seconds."""
        self._record_latency(RUNPOD_POLL_LATENCY, seconds)

    def record_cloudflare_upload_latency(self, seconds: float) -> None:
        """Record Cloudflare R2 upload latency in seconds."""
        self._record_latency(CLOUDFLARE_UPLOAD_LATENCY, seconds)

    def record_r2_upload_latency(self, seconds: float) -> None:
        """Alias for :meth:`record_cloudflare_upload_latency`."""
        self.record_cloudflare_upload_latency(seconds)

    def record_database_latency(self, seconds: float) -> None:
        """Record database persistence latency in seconds."""
        self._record_latency(DATABASE_LATENCY, seconds)

    def record_total_latency(self, seconds: float) -> None:
        """Record end-to-end pipeline latency in seconds."""
        self._record_latency(TOTAL_LATENCY, seconds)

    def record_pipeline_duration(self, seconds: float) -> None:
        """Alias for :meth:`record_total_latency`."""
        self.record_total_latency(seconds)

    def record_llm_latency(self, seconds: float) -> None:
        """Record a generic LLM latency sample (legacy aggregate)."""
        self._record_latency(LLM_LATENCY, seconds)

    def _record_latency(self, metric: str, seconds: float) -> None:
        """Append a duration sample to ``metric``."""
        if seconds < 0:
            raise ValueError("latency must be non-negative")
        if metric not in self._latencies:
            raise ValueError(f"unknown latency metric: {metric}")
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

    def record_retry(self, count: int = 1) -> None:
        """Increase the storyboard/review retry counter."""
        if count < 0:
            raise ValueError("retry count must be non-negative")
        with self._lock:
            self._retry_count += count

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
    def total_tokens(self) -> int:
        """Sum of prompt and completion tokens."""
        with self._lock:
            return self._prompt_tokens + self._completion_tokens

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

    @property
    def retry_count(self) -> int:
        """Total retry attempts recorded."""
        with self._lock:
            return self._retry_count

    def snapshot(self, *, include_samples: bool = False) -> dict[str, Any]:
        """Return all metrics as a JSON-serializable dictionary.

        Args:
            include_samples: When ``True``, include every raw latency sample.

        Returns:
            A dictionary with latency, token, cost, image, and retry metrics.
        """
        with self._lock:
            latency = {
                name: series.to_dict(include_samples=include_samples)
                for name, series in self._latencies.items()
            }
            return {
                "started_at": self._started_at,
                "exported_at": _utc_now_iso(),
                "latency": {
                    "domain_latency": latency[DOMAIN_LATENCY],
                    "research_latency": latency[RESEARCH_LATENCY],
                    "director_latency": latency[DIRECTOR_LATENCY],
                    "prompt_latency": latency[PROMPT_LATENCY],
                    "prompt_composer_latency": latency[PROMPT_COMPOSER_LATENCY],
                    "review_latency": latency[REVIEW_LATENCY],
                    "runpod_latency": latency[RUNPOD_LATENCY],
                    "runpod_submit_latency": latency[RUNPOD_SUBMIT_LATENCY],
                    "runpod_poll_latency": latency[RUNPOD_POLL_LATENCY],
                    "cloudflare_upload_latency": latency[CLOUDFLARE_UPLOAD_LATENCY],
                    "database_latency": latency[DATABASE_LATENCY],
                    "total_latency": latency[TOTAL_LATENCY],
                    # Legacy aggregate kept for older dashboard keys.
                    "llm_latency": latency[LLM_LATENCY],
                },
                "tokens": {
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": self._completion_tokens,
                    "total_tokens": self._prompt_tokens + self._completion_tokens,
                },
                "estimated_cost": round(self._estimated_cost, 6),
                "image_count": self._images_generated,
                "images_generated": self._images_generated,
                "retry_count": self._retry_count,
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

    def export_json(
        self,
        path: str | Path,
        *,
        include_samples: bool = False,
        indent: int | None = 2,
    ) -> Path:
        """Write metrics JSON to ``path`` and return the written path."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            self.to_json(include_samples=include_samples, indent=indent),
            encoding="utf-8",
        )
        return destination

    def reset(self) -> None:
        """Clear every counter and latency series."""
        with self._lock:
            self._started_at = _utc_now_iso()
            self._latencies = {name: LatencySeries() for name in _LATENCY_METRICS}
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._estimated_cost = 0.0
            self._images_generated = 0
            self._retry_count = 0
