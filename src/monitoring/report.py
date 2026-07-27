"""Console and JSON exporters for :class:`PipelineReport`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.monitoring.pipeline_metrics import PipelineReport, StageBreakdown

logger = logging.getLogger(__name__)


def format_cost(amount: float) -> str:
    """Format a USD cost for the console table."""
    return f"${max(0.0, float(amount)):.4f}"


def format_stage_time(duration_ms: float) -> str:
    """Format stage duration as seconds with one decimal place."""
    return f"{max(0.0, float(duration_ms)) / 1000.0:.1f} s"


def format_pipeline_report(report: PipelineReport) -> str:
    """Render the ARAHUS PIPELINE REPORT console summary (cost + images)."""
    name_width = 18
    time_width = 8
    cost_width = 10
    rule = "-" * 47
    banner = "=" * 50

    lines = [
        banner,
        "ARAHUS PIPELINE REPORT",
        banner,
        "",
        f"{'Stage':<{name_width}} {'Time':>{time_width}}  {'Cost':>{cost_width}}",
        rule,
    ]

    for stage in report.stages:
        # Skip empty composer rows with zero time/cost to keep the table clean.
        if (
            stage.name == "Prompt Composer"
            and stage.duration_ms <= 0
            and stage.cost <= 0
        ):
            continue
        cost_cell = format_cost(stage.cost) if stage.cost > 0 or _is_llm_stage(stage) else ""
        lines.append(
            f"{stage.name:<{name_width}} "
            f"{format_stage_time(stage.duration_ms):>{time_width}}  "
            f"{cost_cell:>{cost_width}}"
        )

    if report.image_timings:
        lines.extend(["", "Image Generation", "---------------"])
        for item in sorted(
            report.image_timings,
            key=lambda row: int(row.get("scene_id") or 0),
        ):
            scene_id = int(item.get("scene_id") or 0)
            total_ms = float(item.get("total_ms") or 0.0)
            seconds = int(round(total_ms / 1000.0))
            failed = not bool(item.get("success", True))
            suffix = " (failed)" if failed else ""
            lines.append(f"Scene {scene_id}   {seconds}s{suffix}")
        parallel_s = int(round(float(report.image_parallel_ms) / 1000.0))
        lines.extend(["", f"Total Parallel Time: {parallel_s}s"])

    lines.extend(
        [
            "",
            rule,
            f"{'Total Runtime':<{name_width}} "
            f"{format_stage_time(report.total_runtime_ms):>{time_width}}",
            f"{'LLM Cost':<{name_width}} {format_cost(report.total_llm_cost)}",
            f"{'Input Tokens':<{name_width}} {report.total_input_tokens}",
            f"{'Output Tokens':<{name_width}} {report.total_output_tokens}",
            f"{'Retries':<{name_width}} {report.total_retries}",
            banner,
        ]
    )
    return "\n".join(lines)


def _is_llm_stage(stage: StageBreakdown) -> bool:
    return stage.name in {
        "Domain",
        "Research",
        "Director",
        "Prompt",
        "Review",
    }


def print_pipeline_report(
    report: PipelineReport,
    *,
    log: logging.Logger | None = None,
) -> str:
    """Print / log the console report and return the formatted text."""
    text = format_pipeline_report(report)
    sink = log or logger
    sink.info("event=pipeline_report\n%s", text)
    # Also print for operator-facing CLIs that may not show INFO logs.
    print(text)
    return text


def export_pipeline_report_json(
    report: PipelineReport,
    path: str | Path | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize ``report`` to JSON; optionally write to ``path``.

    Returns:
        The JSON string.
    """
    payload = report.to_dict()
    text = json.dumps(payload, indent=indent, ensure_ascii=False)
    if path is not None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    return text


def report_to_dashboard_metrics(report: PipelineReport) -> dict[str, Any]:
    """Flatten a report into the studio dashboard metrics shape."""
    by_name = {stage.name: stage for stage in report.stages}
    return {
        "pipeline_duration_seconds": round(report.total_runtime_seconds, 6),
        "domain_seconds": round(by_name.get("Domain", StageBreakdown("Domain")).duration_seconds, 6),
        "research_seconds": round(
            by_name.get("Research", StageBreakdown("Research")).duration_seconds, 6
        ),
        "director_seconds": round(
            by_name.get("Director", StageBreakdown("Director")).duration_seconds, 6
        ),
        "prompt_seconds": round(
            by_name.get("Prompt", StageBreakdown("Prompt")).duration_seconds, 6
        ),
        "review_seconds": round(
            by_name.get("Review", StageBreakdown("Review")).duration_seconds, 6
        ),
        "runpod_submit_seconds": round(
            by_name.get("RunPod Submit", StageBreakdown("RunPod Submit")).duration_seconds,
            6,
        ),
        "runpod_poll_seconds": round(
            by_name.get("RunPod Polling", StageBreakdown("RunPod Polling")).duration_seconds,
            6,
        ),
        "cloudflare_seconds": round(
            by_name.get("Cloudflare", StageBreakdown("Cloudflare")).duration_seconds, 6
        ),
        "total_llm_cost": round(report.total_llm_cost, 8),
        "input_tokens": report.total_input_tokens,
        "output_tokens": report.total_output_tokens,
        "retries": report.total_retries,
        "slowest_stage": report.slowest_stage,
        "most_expensive_stage": report.most_expensive_stage,
        "image_parallel_seconds": round(report.image_parallel_seconds, 6),
        "image_timings": list(report.image_timings),
        "pipeline_report": report.to_dict(),
    }
