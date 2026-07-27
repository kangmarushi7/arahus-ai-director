"""Unit tests for the pipeline profiler, timer, and metrics report."""

from __future__ import annotations

import logging
import time

import pytest

from src.monitoring.metrics import (
    RESEARCH_LATENCY,
    STAGE_DATABASE,
    STAGE_DOMAIN_DETECTION,
    STAGE_RESEARCH,
    MetricsCollector,
    PipelineMetrics,
    StageMetrics,
    format_duration_ms,
)
from src.monitoring.profiler import (
    PipelineProfiler,
    get_profiler,
    measure_stage,
)
from src.monitoring.timer import Timer, timed, utc_now


def test_timer_records_duration_and_timestamps() -> None:
    timer = Timer.start_new()
    time.sleep(0.01)
    duration_ms = timer.stop()
    assert duration_ms >= 10.0
    assert timer.start_time is not None
    assert timer.end_time is not None
    assert timer.end_time >= timer.start_time
    assert timer.duration_ms == duration_ms


def test_timed_context_manager_stops_on_error() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with timed() as timer:
            time.sleep(0.005)
            raise RuntimeError("boom")
    assert not timer.running
    assert timer.duration_ms >= 5.0


def test_format_duration_ms() -> None:
    assert format_duration_ms(320) == "320 ms"
    assert format_duration_ms(41_200) == "41.2 s"
    assert format_duration_ms(0) == "0 ms"


def test_pipeline_metrics_format_table() -> None:
    started = utc_now()
    report = PipelineMetrics(
        started_at=started,
        finished_at=started,
        total_duration_ms=144_900.0,
    )
    report.add_stage(
        StageMetrics(
            stage=STAGE_DOMAIN_DETECTION,
            start_time=started,
            end_time=started,
            duration_ms=320.0,
            success=True,
        )
    )
    report.add_stage(
        StageMetrics(
            stage=STAGE_RESEARCH,
            start_time=started,
            end_time=started,
            duration_ms=41_200.0,
            success=True,
        )
    )
    table = report.format_table()
    assert "Stage" in table
    assert "Domain Detection" in table
    assert "320 ms" in table
    assert "Research" in table
    assert "41.2 s" in table
    assert "Total" in table
    assert "144.9 s" in table


def test_profiler_measure_success_and_failure() -> None:
    collector = MetricsCollector()
    profiler = PipelineProfiler(collector, topic="test", print_table=False)
    profiler.start()

    with profiler.measure(STAGE_RESEARCH):
        time.sleep(0.01)

    with pytest.raises(ValueError, match="nope"):
        with profiler.measure(STAGE_DOMAIN_DETECTION):
            raise ValueError("nope")

    report = profiler.finish()
    assert len(report.stages) == 2
    assert report.stages[0].success is True
    assert report.stages[0].duration_ms >= 10.0
    assert report.stages[1].success is False
    assert report.stages[1].error is not None
    assert "ValueError" in report.stages[1].error
    assert collector.snapshot()["latency"][RESEARCH_LATENCY]["count"] == 1


def test_measure_stage_binds_to_profiler() -> None:
    profiler = PipelineProfiler(print_table=False)
    profiler.start()
    with profiler.bind():
        assert get_profiler() is profiler
        with measure_stage(STAGE_DATABASE):
            time.sleep(0.005)
    assert get_profiler() is None
    report = profiler.finish()
    assert len(report.stages) == 1
    assert report.stages[0].stage == STAGE_DATABASE


def test_measure_stage_unbound_still_logs(caplog: pytest.LogCaptureFixture) -> None:
    assert get_profiler() is None
    with caplog.at_level(logging.INFO, logger="src.monitoring.profiler"):
        with measure_stage(STAGE_DATABASE):
            time.sleep(0.005)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "event=stage_start" in messages
    assert "event=stage_complete" in messages
    assert STAGE_DATABASE in messages


def test_profiler_log_report_emits_table(caplog: pytest.LogCaptureFixture) -> None:
    profiler = PipelineProfiler(topic="demo", print_table=True)
    profiler.start()
    with profiler.measure(STAGE_RESEARCH):
        time.sleep(0.005)
    with caplog.at_level(logging.INFO, logger="src.monitoring.profiler"):
        report = profiler.log_report()
    assert report.total_duration_ms >= 5.0
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=pipeline_metrics_table" in messages
    assert "Research" in messages
    assert "Total" in messages
