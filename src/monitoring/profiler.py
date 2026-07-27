"""Production pipeline stage profiler.

Times each pipeline stage, records success/error, feeds the existing
:class:`~src.monitoring.metrics.MetricsCollector`, and emits a pretty
console table via structured logging.

Usage::

    profiler = PipelineProfiler(collector=metrics, topic=topic)
    with profiler.bind():
        with profiler.measure(STAGE_RESEARCH):
            research_agent.run(topic)
    report = profiler.finish()
    profiler.log_report()

Nested call sites (RunPod, R2, PromptComposer, DB sync) can use
:func:`measure_stage` which no-ops when no profiler is bound.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from src.monitoring.metrics import (
    STAGE_TO_METRIC,
    MetricsCollector,
    PipelineMetrics,
    StageMetrics,
)
from src.monitoring.timer import Timer, utc_now

logger = logging.getLogger(__name__)

_current_profiler: ContextVar[PipelineProfiler | None] = ContextVar(
    "pipeline_profiler",
    default=None,
)


def get_profiler() -> PipelineProfiler | None:
    """Return the profiler bound to the current context, if any."""
    return _current_profiler.get()


class PipelineProfiler:
    """Collect per-stage timings for a single pipeline run.

    Thread-safe for concurrent stage samples (e.g. parallel image renders).
    Wall-clock total is measured from :meth:`start` through :meth:`finish`.
    """

    def __init__(
        self,
        collector: MetricsCollector | None = None,
        *,
        topic: str | None = None,
        log: logging.Logger | None = None,
        print_table: bool = True,
    ) -> None:
        """Create a profiler for one pipeline execution.

        Args:
            collector: Optional :class:`MetricsCollector` to receive latency
                samples for known stage→metric mappings.
            topic: Optional topic label stored on the final report.
            log: Logger used for stage events and the console table.
            print_table: When ``True``, :meth:`log_report` emits the table.
        """
        self._collector = collector
        self._topic = topic
        self._logger = log or logger
        self._print_table = print_table
        self._lock = threading.RLock()
        self._report = PipelineMetrics(topic=topic)
        self._run_timer: Timer | None = None
        self._finished = False
        self._bind_token: Token[PipelineProfiler | None] | None = None

    @property
    def report(self) -> PipelineMetrics:
        """Current (possibly in-progress) metrics report."""
        return self._report

    @property
    def collector(self) -> MetricsCollector | None:
        """Optional metrics collector receiving latency samples."""
        return self._collector

    def start(self, *, topic: str | None = None) -> PipelineProfiler:
        """Begin wall-clock timing for the overall pipeline run."""
        with self._lock:
            if self._finished:
                raise RuntimeError("profiler already finished; create a new instance")
            if topic is not None:
                self._topic = topic
                self._report.topic = topic
            self._report.started_at = utc_now()
            self._run_timer = Timer.start_new()
        self._logger.info(
            "event=profiler_start topic=%r",
            self._topic,
        )
        return self

    def finish(self, *, error: str | None = None) -> PipelineMetrics:
        """Stop the run timer and return the final :class:`PipelineMetrics`."""
        with self._lock:
            if self._finished:
                return self._report
            if self._run_timer is not None and self._run_timer.running:
                self._run_timer.stop()
            finished_at = utc_now()
            total_ms = (
                self._run_timer.duration_ms if self._run_timer is not None else 0.0
            )
            self._report.finished_at = finished_at
            self._report.total_duration_ms = total_ms
            if error:
                self._report.success = False
                self._report.error = error
            self._finished = True

            if self._collector is not None:
                self._collector.record_total_latency(total_ms / 1000.0)

        self._logger.info(
            "event=profiler_finish topic=%r total_ms=%.1f success=%s stages=%s",
            self._topic,
            self._report.total_duration_ms,
            self._report.success,
            len(self._report.stages),
        )
        return self._report

    def log_report(self) -> PipelineMetrics:
        """Ensure the report is finished, then log the console table."""
        report = self.finish() if not self._finished else self._report
        table = report.format_table()
        if self._print_table:
            # Emit as a single log record so handlers keep the table intact.
            self._logger.info(
                "event=pipeline_metrics_table topic=%r\n%s",
                self._topic,
                table,
            )
        return report

    @contextmanager
    def bind(self) -> Iterator[PipelineProfiler]:
        """Bind this profiler to the current context for nested ``measure_stage``."""
        token = _current_profiler.set(self)
        self._bind_token = token
        try:
            yield self
        finally:
            _current_profiler.reset(token)
            self._bind_token = None

    @contextmanager
    def measure(self, stage: str, *, metric: str | None = None) -> Iterator[None]:
        """Time ``stage``, record outcome, and optionally feed ``metric``.

        Args:
            stage: Human-readable stage name (see ``STAGE_*`` constants).
            metric: Optional :class:`MetricsCollector` latency key. When omitted,
                looks up :data:`~src.monitoring.metrics.STAGE_TO_METRIC`.

        Yields:
            ``None`` while the timed block executes.

        Notes:
            Exceptions propagate after the stage is recorded as failed.
        """
        metric_name = metric if metric is not None else STAGE_TO_METRIC.get(stage)
        timer = Timer.start_new()
        error: str | None = None
        success = True
        self._logger.info("event=stage_start stage=%s", stage)
        try:
            yield
        except Exception as exc:
            success = False
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if timer.running:
                timer.stop()
            sample = StageMetrics(
                stage=stage,
                start_time=timer.start_time or utc_now(),
                end_time=timer.end_time or utc_now(),
                duration_ms=timer.duration_ms,
                success=success,
                error=error,
            )
            with self._lock:
                self._report.add_stage(sample)
                if metric_name is not None and self._collector is not None:
                    try:
                        self._collector._record_latency(  # noqa: SLF001
                            metric_name,
                            sample.duration_ms / 1000.0,
                        )
                    except ValueError:
                        self._logger.warning(
                            "event=profiler_unknown_metric stage=%s metric=%s",
                            stage,
                            metric_name,
                        )

            self._logger.info(
                "event=stage_complete stage=%s duration_ms=%.1f success=%s error=%r",
                stage,
                sample.duration_ms,
                sample.success,
                sample.error,
            )


@contextmanager
def measure_stage(stage: str, *, metric: str | None = None) -> Iterator[None]:
    """Measure ``stage`` on the bound profiler, or log timing when unbound.

    Safe to call from nested services (RunPod, R2, composer, persistence)
    without changing their public APIs. When no profiler is bound the block
    still times and emits ``stage_start`` / ``stage_complete`` log events so
    post-pipeline work (e.g. database sync) remains observable.
    """
    profiler = get_profiler()
    if profiler is not None:
        with profiler.measure(stage, metric=metric):
            yield
        return

    timer = Timer.start_new()
    error: str | None = None
    success = True
    logger.info("event=stage_start stage=%s", stage)
    try:
        yield
    except Exception as exc:
        success = False
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if timer.running:
            timer.stop()
        logger.info(
            "event=stage_complete stage=%s duration_ms=%.1f success=%s error=%r",
            stage,
            timer.duration_ms,
            success,
            error,
        )

@contextmanager
def profiled_pipeline(
    collector: MetricsCollector | None = None,
    *,
    topic: str | None = None,
    log: logging.Logger | None = None,
    print_table: bool = True,
) -> Iterator[PipelineProfiler]:
    """Start, bind, and finish a :class:`PipelineProfiler` around a block.

    On exit (success or failure) the profiler is finished and the console
    table is logged when ``print_table`` is enabled.
    """
    profiler = PipelineProfiler(
        collector=collector,
        topic=topic,
        log=log,
        print_table=print_table,
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
            if print_table:
                profiler.log_report()
