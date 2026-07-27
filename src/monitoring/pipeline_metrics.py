"""Pipeline run report models (cost + timing)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.monitoring.cost_tracker import LLMCallRecord
from src.monitoring.metrics import (
    STAGE_CLOUDFLARE_UPLOAD,
    STAGE_DATABASE,
    STAGE_DIRECTOR,
    STAGE_DOMAIN_DETECTION,
    STAGE_PROMPT,
    STAGE_PROMPT_COMPOSER,
    STAGE_RESEARCH,
    STAGE_REVIEW,
    STAGE_RUNPOD_POLL,
    STAGE_RUNPOD_SUBMIT,
)

# Short console labels (Sprint 4.2 report format).
REPORT_STAGE_LABELS: dict[str, str] = {
    STAGE_DOMAIN_DETECTION: "Domain",
    STAGE_RESEARCH: "Research",
    STAGE_DIRECTOR: "Director",
    STAGE_PROMPT: "Prompt",
    STAGE_PROMPT_COMPOSER: "Prompt Composer",
    STAGE_REVIEW: "Review",
    STAGE_RUNPOD_SUBMIT: "RunPod Submit",
    STAGE_RUNPOD_POLL: "RunPod Polling",
    STAGE_CLOUDFLARE_UPLOAD: "Cloudflare",
    STAGE_DATABASE: "Database",
}

# Map LLM router tasks → report stage labels for cost attribution.
TASK_TO_REPORT_STAGE: dict[str, str] = {
    "domain": "Domain",
    "research": "Research",
    "director": "Director",
    "prompt": "Prompt",
    "review": "Review",
    "general": "Prompt",
}

REPORT_STAGE_ORDER: tuple[str, ...] = (
    "Domain",
    "Research",
    "Director",
    "Prompt",
    "Prompt Composer",
    "Review",
    "RunPod Submit",
    "RunPod Polling",
    "Cloudflare",
    "Database",
)


@dataclass(slots=True)
class StageBreakdown:
    """One row in the pipeline cost/timing report."""

    name: str
    duration_ms: float = 0.0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    count: int = 1
    success: bool = True

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 3),
            "duration_seconds": round(self.duration_seconds, 6),
            "cost": round(self.cost, 8),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "retries": self.retries,
            "count": self.count,
            "success": self.success,
        }


@dataclass(slots=True)
class PipelineReport:
    """Full observability snapshot for one pipeline execution."""

    topic: str | None = None
    total_runtime_ms: float = 0.0
    total_llm_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_retries: int = 0
    stages: list[StageBreakdown] = field(default_factory=list)
    slowest_stage: str | None = None
    most_expensive_stage: str | None = None
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    image_timings: list[dict[str, Any]] = field(default_factory=list)
    image_parallel_ms: float = 0.0
    success: bool = True
    error: str | None = None

    @property
    def total_runtime_seconds(self) -> float:
        return self.total_runtime_ms / 1000.0

    @property
    def image_parallel_seconds(self) -> float:
        return self.image_parallel_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "total_runtime_ms": round(self.total_runtime_ms, 3),
            "total_runtime_seconds": round(self.total_runtime_seconds, 6),
            "total_llm_cost": round(self.total_llm_cost, 8),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_retries": self.total_retries,
            "slowest_stage": self.slowest_stage,
            "most_expensive_stage": self.most_expensive_stage,
            "success": self.success,
            "error": self.error,
            "stages": [stage.to_dict() for stage in self.stages],
            "llm_calls": [call.to_dict() for call in self.llm_calls],
            "image_timings": list(self.image_timings),
            "image_parallel_ms": round(self.image_parallel_ms, 3),
            "image_parallel_seconds": round(self.image_parallel_seconds, 6),
        }


def build_pipeline_report(
    *,
    topic: str | None,
    total_runtime_ms: float,
    stage_durations: dict[str, float],
    stage_success: dict[str, bool] | None = None,
    stage_counts: dict[str, int] | None = None,
    llm_calls: list[LLMCallRecord] | None = None,
    extra_retries: int = 0,
    success: bool = True,
    error: str | None = None,
) -> PipelineReport:
    """Assemble a :class:`PipelineReport` from stage timings + LLM call records.

    Args:
        topic: Optional topic label.
        total_runtime_ms: Wall-clock pipeline duration.
        stage_durations: Map of profiler stage name → duration_ms (summed).
        stage_success: Optional map of stage → success flag.
        stage_counts: Optional map of stage → sample count.
        llm_calls: LLM call records from :class:`CostTracker`.
        extra_retries: Non-LLM retries (storyboard regeneration, etc.).
        success: Overall run success.
        error: Optional error summary.
    """
    calls = list(llm_calls or [])
    success_map = stage_success or {}
    count_map = stage_counts or {}

    cost_by_label: dict[str, float] = {}
    tokens_by_label: dict[str, tuple[int, int]] = {}
    retries_by_label: dict[str, int] = {}
    for call in calls:
        label = TASK_TO_REPORT_STAGE.get(call.task, call.task.title())
        cost_by_label[label] = cost_by_label.get(label, 0.0) + call.estimated_cost
        inp, out = tokens_by_label.get(label, (0, 0))
        tokens_by_label[label] = (inp + call.input_tokens, out + call.output_tokens)
        retries_by_label[label] = retries_by_label.get(label, 0) + call.retries

    # Normalize profiler stage names → report labels and sum durations.
    duration_by_label: dict[str, float] = {}
    success_by_label: dict[str, bool] = {}
    count_by_label: dict[str, int] = {}
    for stage_name, duration_ms in stage_durations.items():
        label = REPORT_STAGE_LABELS.get(stage_name, stage_name)
        duration_by_label[label] = duration_by_label.get(label, 0.0) + float(duration_ms)
        if label in success_by_label:
            success_by_label[label] = success_by_label[label] and success_map.get(
                stage_name, True
            )
        else:
            success_by_label[label] = success_map.get(stage_name, True)
        count_by_label[label] = count_by_label.get(label, 0) + int(
            count_map.get(stage_name, 1)
        )

    labels = [name for name in REPORT_STAGE_ORDER if name in duration_by_label]
    labels.extend(name for name in duration_by_label if name not in REPORT_STAGE_ORDER)
    # Include cost-only labels (edge case) that never got a duration sample.
    for label in cost_by_label:
        if label not in labels:
            labels.append(label)

    stages: list[StageBreakdown] = []
    for label in labels:
        inp, out = tokens_by_label.get(label, (0, 0))
        stages.append(
            StageBreakdown(
                name=label,
                duration_ms=duration_by_label.get(label, 0.0),
                cost=cost_by_label.get(label, 0.0),
                input_tokens=inp,
                output_tokens=out,
                retries=retries_by_label.get(label, 0),
                count=max(1, count_by_label.get(label, 1)),
                success=success_by_label.get(label, True),
            )
        )

    total_cost = sum(call.estimated_cost for call in calls)
    total_retries = extra_retries + sum(call.retries for call in calls)
    slowest = max(stages, key=lambda s: s.duration_ms).name if stages else None
    expensive = (
        max(stages, key=lambda s: s.cost).name
        if stages and any(s.cost > 0 for s in stages)
        else None
    )

    return PipelineReport(
        topic=topic,
        total_runtime_ms=float(total_runtime_ms),
        total_llm_cost=total_cost,
        total_input_tokens=sum(call.input_tokens for call in calls),
        total_output_tokens=sum(call.output_tokens for call in calls),
        total_retries=total_retries,
        stages=stages,
        slowest_stage=slowest,
        most_expensive_stage=expensive,
        llm_calls=calls,
        success=success,
        error=error,
    )
