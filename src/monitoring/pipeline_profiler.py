"""Pipeline profiler with cost tracking and Sprint 4.2 reports.

This module is the Sprint 4.2 entry point. It reuses the battle-tested
:class:`~src.monitoring.profiler.PipelineProfiler` for stage timing and adds
:class:`~src.monitoring.cost_tracker.CostTracker` + :class:`PipelineReport`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from src.monitoring.cost_tracker import (
    CostTracker,
    bind_cost_tracker,
    get_cost_tracker,
    reset_cost_tracker,
)
from src.monitoring.metrics import MetricsCollector, PipelineMetrics
from src.monitoring.pipeline_metrics import PipelineReport, build_pipeline_report
from src.monitoring.profiler import (
    PipelineProfiler as _StageProfiler,
)
from src.monitoring.profiler import (
    get_profiler,
    measure_stage,
)
from src.monitoring.report import (
    export_pipeline_report_json,
    format_pipeline_report,
    print_pipeline_report,
    report_to_dashboard_metrics,
)

logger = logging.getLogger(__name__)


class PipelineProfiler(_StageProfiler):
    """Stage profiler that also owns a per-run :class:`CostTracker`."""

    def __init__(
        self,
        collector: MetricsCollector | None = None,
        *,
        topic: str | None = None,
        log: logging.Logger | None = None,
        print_table: bool = True,
        cost_tracker: CostTracker | None = None,
        print_cost_report: bool = True,
    ) -> None:
        super().__init__(
            collector=collector,
            topic=topic,
            log=log,
            print_table=print_table,
        )
        self._cost_tracker = cost_tracker or CostTracker()
        self._print_cost_report = print_cost_report
        self._cost_token = None
        self._pipeline_report: PipelineReport | None = None
        self._image_timings: list[dict] = []
        self._image_parallel_ms: float = 0.0

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker

    @property
    def pipeline_report(self) -> PipelineReport | None:
        """Final Sprint 4.2 report, available after :meth:`build_pipeline_report`."""
        return self._pipeline_report

    def record_image_batch(
        self,
        *,
        timings: list[dict],
        total_parallel_ms: float,
    ) -> None:
        """Attach Sprint 4.3 parallel image timings to the upcoming report."""
        self._image_timings = list(timings)
        self._image_parallel_ms = float(total_parallel_ms)

    def record_storyboard_retry(self, count: int = 1) -> None:
        """Record a non-LLM storyboard regeneration retry."""
        self._cost_tracker.record_retry(count)

    @contextmanager
    def bind(self) -> Iterator[PipelineProfiler]:
        """Bind stage profiler + cost tracker to the current context."""
        with super().bind():
            token = bind_cost_tracker(self._cost_tracker)
            self._cost_token = token
            try:
                yield self
            finally:
                reset_cost_tracker(token)
                self._cost_token = None

    def build_pipeline_report(self) -> PipelineReport:
        """Compose the Sprint 4.2 :class:`PipelineReport` from timings + costs."""
        report_metrics: PipelineMetrics = self.report
        durations: dict[str, float] = {}
        success: dict[str, bool] = {}
        counts: dict[str, int] = {}
        for sample in report_metrics.stages:
            durations[sample.stage] = durations.get(sample.stage, 0.0) + sample.duration_ms
            counts[sample.stage] = counts.get(sample.stage, 0) + 1
            if sample.stage in success:
                success[sample.stage] = success[sample.stage] and sample.success
            else:
                success[sample.stage] = sample.success

        self._pipeline_report = build_pipeline_report(
            topic=report_metrics.topic,
            total_runtime_ms=report_metrics.total_duration_ms,
            stage_durations=durations,
            stage_success=success,
            stage_counts=counts,
            llm_calls=self._cost_tracker.calls,
            extra_retries=0,  # included via cost_tracker.record_retry
            success=report_metrics.success,
            error=report_metrics.error,
        )
        # Prefer tracker total (LLM retries + storyboard retries).
        self._pipeline_report.total_retries = self._cost_tracker.total_retries
        self._pipeline_report.image_timings = list(self._image_timings)
        self._pipeline_report.image_parallel_ms = self._image_parallel_ms
        return self._pipeline_report

    def log_report(self) -> PipelineMetrics:
        """Log legacy stage table, then the Sprint 4.2 cost report."""
        metrics = super().log_report()
        report = self.build_pipeline_report()
        if self._print_cost_report:
            print_pipeline_report(report, log=self._logger)
        return metrics

    def export_json(self, path: str | None = None) -> str:
        """Export the Sprint 4.2 report as JSON (optionally to ``path``)."""
        report = self._pipeline_report or self.build_pipeline_report()
        return export_pipeline_report_json(report, path)


@contextmanager
def profiled_pipeline(
    collector: MetricsCollector | None = None,
    *,
    topic: str | None = None,
    log: logging.Logger | None = None,
    print_table: bool = True,
    print_cost_report: bool = True,
) -> Iterator[PipelineProfiler]:
    """Start, bind, and finish a cost-aware :class:`PipelineProfiler`."""
    profiler = PipelineProfiler(
        collector=collector,
        topic=topic,
        log=log,
        print_table=print_table,
        print_cost_report=print_cost_report,
    )
    profiler.start(topic=topic)
    error: str | None = None
    with profiler.bind():
        try:
            yield profiler
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            profiler.finish(error=error)
            if print_table or print_cost_report:
                profiler.log_report()


__all__ = [
    "PipelineProfiler",
    "export_pipeline_report_json",
    "format_pipeline_report",
    "get_cost_tracker",
    "get_profiler",
    "measure_stage",
    "print_pipeline_report",
    "profiled_pipeline",
    "report_to_dashboard_metrics",
]
