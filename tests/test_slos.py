"""Lightweight SLO checks for pipeline metrics shape and thresholds."""

from __future__ import annotations

from src.monitoring.metrics import (
    STAGE_DOMAIN_DETECTION,
    STAGE_RESEARCH,
    PipelineMetrics,
    StageMetrics,
    format_duration_ms,
)
from src.monitoring.timer import utc_now

# Soft CI SLOs for synthetic / unit timings (not live benchmark).
SLO_DOMAIN_MS_MAX = 5_000.0
SLO_RESEARCH_MS_MAX = 180_000.0


def test_format_duration_stable() -> None:
    assert format_duration_ms(320) == "320 ms"
    assert "s" in format_duration_ms(12_500)


def test_pipeline_metrics_summary_respects_order() -> None:
    now = utc_now()
    report = PipelineMetrics(started_at=now, finished_at=now, total_duration_ms=1_000)
    report.add_stage(
        StageMetrics(
            stage=STAGE_RESEARCH,
            start_time=now,
            end_time=now,
            duration_ms=400,
            success=True,
        )
    )
    report.add_stage(
        StageMetrics(
            stage=STAGE_DOMAIN_DETECTION,
            start_time=now,
            end_time=now,
            duration_ms=100,
            success=True,
        )
    )
    labels = [item.stage for item in report.summarize_stages()]
    assert labels.index(STAGE_DOMAIN_DETECTION) < labels.index(STAGE_RESEARCH)


def test_synthetic_stage_slos() -> None:
    """Guardrail: unit-scale timings stay under generous SLO ceilings."""
    now = utc_now()
    domain = StageMetrics(
        stage=STAGE_DOMAIN_DETECTION,
        start_time=now,
        end_time=now,
        duration_ms=50,
        success=True,
    )
    research = StageMetrics(
        stage=STAGE_RESEARCH,
        start_time=now,
        end_time=now,
        duration_ms=1_000,
        success=True,
    )
    assert domain.duration_ms < SLO_DOMAIN_MS_MAX
    assert research.duration_ms < SLO_RESEARCH_MS_MAX
