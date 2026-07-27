"""Unit tests for Sprint 4.2 cost tracking and pipeline reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm.config import parse_router_config
from src.llm.exceptions import LLMProviderError, LLMRateLimitError
from src.llm.metrics import LLMMetrics
from src.llm.models import LLMResponse, ProviderCompletion
from src.llm.retry import RetryPolicy, RetryState, call_with_retry
from src.llm.router import LLMRouter
from src.monitoring.cost_tracker import (
    CostTracker,
    LLMCallRecord,
    bind_cost_tracker,
    get_cost_tracker,
    reset_cost_tracker,
)
from src.monitoring.metrics import (
    STAGE_DIRECTOR,
    STAGE_DOMAIN_DETECTION,
    STAGE_RESEARCH,
    STAGE_RUNPOD_POLL,
    MetricsCollector,
)
from src.monitoring.pipeline_metrics import (
    PipelineReport,
    StageBreakdown,
    build_pipeline_report,
)
from src.monitoring.pipeline_profiler import PipelineProfiler
from src.monitoring.report import (
    export_pipeline_report_json,
    format_cost,
    format_pipeline_report,
    format_stage_time,
    print_pipeline_report,
    report_to_dashboard_metrics,
)


class _FakeProvider:
    def __init__(self, *, text: str = "ok", fail_times: int = 0) -> None:
        self.name = "openrouter"
        self.text = text
        self.fail_times = fail_times
        self.calls = 0

    def complete(
        self,
        *,
        model: str,
        messages: object,
        temperature: float,
        max_tokens: int,
        response_format: object = None,
    ) -> ProviderCompletion:
        del messages, temperature, max_tokens, response_format
        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMRateLimitError("429", provider="openrouter", model=model)
        return ProviderCompletion(
            text=self.text,
            model=model,
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
        )


def _sample_config_dict() -> dict:
    return {
        "default_provider": "openrouter",
        "providers": {
            "openrouter": {
                "type": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "timeout_seconds": 30,
            }
        },
        "tasks": {
            "research": {"provider": "openrouter", "model": "test/model-a"},
            "director": {"provider": "openrouter", "model": "test/model-a"},
            "general": {"provider": "openrouter", "model": "test/model-a"},
        },
        "pricing": {
            "default": {"input_per_million": 1.0, "output_per_million": 2.0},
            "test/model-a": {"input_per_million": 1.0, "output_per_million": 2.0},
        },
        "retry": {
            "max_attempts": 3,
            "base_delay_seconds": 0.0,
            "max_delay_seconds": 0.0,
            "jitter_ratio": 0.0,
        },
    }


class TestCostTracker:
    def test_records_llm_calls_and_totals(self) -> None:
        tracker = CostTracker()
        tracker.record_llm_call(
            task="Research",
            provider="openrouter",
            model="m",
            input_tokens=10,
            output_tokens=5,
            latency_ms=12.5,
            estimated_cost=0.001,
            retries=1,
        )
        tracker.record_response(
            LLMResponse(
                text="x",
                provider="openrouter",
                model="m",
                input_tokens=20,
                output_tokens=10,
                latency_ms=30.0,
                estimated_cost=0.002,
                task="director",
            ),
            retries=0,
        )
        tracker.record_retry(2)

        assert len(tracker.calls) == 2
        assert tracker.calls[0].task == "research"
        assert tracker.total_input_tokens == 30
        assert tracker.total_output_tokens == 15
        assert tracker.total_llm_cost == pytest.approx(0.003)
        assert tracker.total_retries == 3  # 1 + 0 + 2 extra
        assert tracker.cost_by_task()["research"] == pytest.approx(0.001)
        assert tracker.cost_by_task()["director"] == pytest.approx(0.002)

    def test_context_bind_and_reset(self) -> None:
        assert get_cost_tracker() is None
        tracker = CostTracker()
        token = bind_cost_tracker(tracker)
        try:
            assert get_cost_tracker() is tracker
        finally:
            reset_cost_tracker(token)
        assert get_cost_tracker() is None

    def test_to_dict_serializable(self) -> None:
        tracker = CostTracker()
        tracker.record_llm_call(
            task="prompt",
            provider="openrouter",
            model="m",
            input_tokens=1,
            output_tokens=2,
            estimated_cost=0.5,
        )
        payload = tracker.to_dict()
        assert payload["total_input_tokens"] == 1
        assert payload["calls"][0]["task"] == "prompt"
        json.dumps(payload)  # must be JSON-safe


class TestPipelineReport:
    def test_build_report_stage_breakdown(self) -> None:
        calls = [
            LLMCallRecord(
                task="research",
                provider="openrouter",
                model="m",
                input_tokens=1000,
                output_tokens=200,
                estimated_cost=0.0021,
                retries=1,
            ),
            LLMCallRecord(
                task="director",
                provider="openrouter",
                model="m",
                input_tokens=2000,
                output_tokens=400,
                estimated_cost=0.0054,
            ),
        ]
        report = build_pipeline_report(
            topic="Fall of Constantinople",
            total_runtime_ms=60_000.0,
            stage_durations={
                STAGE_DOMAIN_DETECTION: 300.0,
                STAGE_RESEARCH: 4_200.0,
                STAGE_DIRECTOR: 6_800.0,
                STAGE_RUNPOD_POLL: 42_100.0,
            },
            llm_calls=calls,
            extra_retries=1,
        )
        assert isinstance(report, PipelineReport)
        assert report.total_runtime_ms == 60_000.0
        assert report.total_llm_cost == pytest.approx(0.0075)
        assert report.total_input_tokens == 3000
        assert report.total_output_tokens == 600
        assert report.total_retries == 2
        assert report.slowest_stage == "RunPod Polling"
        assert report.most_expensive_stage == "Director"

        by_name = {stage.name: stage for stage in report.stages}
        assert by_name["Research"].cost == pytest.approx(0.0021)
        assert by_name["Research"].duration_ms == 4_200.0
        assert by_name["RunPod Polling"].cost == 0.0

    def test_format_console_summary(self) -> None:
        report = PipelineReport(
            topic="t",
            total_runtime_ms=60_000.0,
            total_llm_cost=0.0102,
            total_input_tokens=12345,
            total_output_tokens=678,
            total_retries=2,
            stages=[
                StageBreakdown(name="Domain", duration_ms=300.0, cost=0.0),
                StageBreakdown(name="Research", duration_ms=4_200.0, cost=0.0021),
                StageBreakdown(name="RunPod Polling", duration_ms=42_100.0),
            ],
            slowest_stage="RunPod Polling",
            most_expensive_stage="Research",
        )
        text = format_pipeline_report(report)
        assert "ARAHUS PIPELINE REPORT" in text
        assert "Domain" in text
        assert "0.3 s" in text
        assert "$0.0021" in text
        assert "Total Runtime" in text
        assert "60.0 s" in text
        assert "LLM Cost" in text
        assert "$0.0102" in text
        assert "Input Tokens" in text
        assert "12345" in text
        assert "Retries" in text
        # Keep console summary tight — details live in JSON.
        assert "Slowest Stage" not in text

    def test_format_helpers(self) -> None:
        assert format_cost(0.0102) == "$0.0102"
        assert format_stage_time(4200) == "4.2 s"

    def test_export_json(self, tmp_path: Path) -> None:
        report = build_pipeline_report(
            topic="Mars",
            total_runtime_ms=1000.0,
            stage_durations={STAGE_RESEARCH: 500.0},
            llm_calls=[
                LLMCallRecord(
                    task="research",
                    provider="openrouter",
                    model="m",
                    input_tokens=10,
                    output_tokens=5,
                    estimated_cost=0.001,
                )
            ],
        )
        path = tmp_path / "report.json"
        text = export_pipeline_report_json(report, path)
        payload = json.loads(text)
        assert payload["topic"] == "Mars"
        assert payload["total_llm_cost"] == pytest.approx(0.001)
        assert path.read_text(encoding="utf-8") == text
        assert "stages" in payload
        assert "llm_calls" in payload

    def test_dashboard_flatten(self) -> None:
        report = build_pipeline_report(
            topic="t",
            total_runtime_ms=10_000.0,
            stage_durations={STAGE_RESEARCH: 4_000.0},
            llm_calls=[],
        )
        flat = report_to_dashboard_metrics(report)
        assert flat["pipeline_duration_seconds"] == pytest.approx(10.0)
        assert flat["research_seconds"] == pytest.approx(4.0)
        assert "pipeline_report" in flat


class TestPipelineProfilerCostIntegration:
    def test_bind_tracks_llm_via_router(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text="hello")
        router = LLMRouter(cfg, providers={"openrouter": provider}, metrics=LLMMetrics())
        profiler = PipelineProfiler(
            MetricsCollector(),
            topic="Bitcoin",
            print_table=False,
            print_cost_report=False,
        )
        profiler.start()
        with profiler.bind():
            with profiler.measure(STAGE_RESEARCH):
                response = router.generate(
                    task="research",
                    messages=[{"role": "user", "content": "hi"}],
                )
            assert response.input_tokens == 100
            assert get_cost_tracker() is profiler.cost_tracker

        profiler.finish()
        report = profiler.build_pipeline_report()
        assert report.total_input_tokens == 100
        assert report.total_output_tokens == 50
        assert report.total_llm_cost > 0
        assert report.stages
        assert any(stage.name == "Research" for stage in report.stages)
        assert get_cost_tracker() is None

    def test_router_records_retries(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text="recovered", fail_times=2)
        router = LLMRouter(cfg, providers={"openrouter": provider})
        profiler = PipelineProfiler(print_table=False, print_cost_report=False)
        profiler.start()
        with profiler.bind():
            router.generate(
                task="general",
                messages=[{"role": "user", "content": "x"}],
            )
        profiler.finish()
        report = profiler.build_pipeline_report()
        assert report.total_retries == 2
        assert profiler.cost_tracker.calls[0].retries == 2

    def test_storyboard_retry_counted(self) -> None:
        profiler = PipelineProfiler(print_table=False, print_cost_report=False)
        profiler.start()
        with profiler.bind():
            with profiler.measure(STAGE_DOMAIN_DETECTION):
                pass
            profiler.record_storyboard_retry(1)
        profiler.finish()
        report = profiler.build_pipeline_report()
        assert report.total_retries == 1

    def test_print_report_emits_console(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = PipelineReport(
            total_runtime_ms=1000.0,
            total_llm_cost=0.0,
            stages=[StageBreakdown(name="Domain", duration_ms=300.0)],
        )
        print_pipeline_report(report)
        captured = capsys.readouterr()
        assert "ARAHUS PIPELINE REPORT" in captured.out


class TestRetryState:
    def test_retry_state_tracks_failures(self) -> None:
        calls = {"n": 0}
        state = RetryState()

        def op() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMRateLimitError("429", provider="x", model="y")
            return "ok"

        result = call_with_retry(
            op,
            policy=RetryPolicy(
                max_attempts=3,
                base_delay_seconds=0.0,
                max_delay_seconds=0.0,
                jitter_ratio=0.0,
            ),
            state=state,
        )
        assert result == "ok"
        assert state.retries == 2

    def test_hard_failure_records_retries_attempted(self) -> None:
        state = RetryState()
        calls = {"n": 0}

        def op() -> str:
            calls["n"] += 1
            raise LLMProviderError("nope", provider="x", model="y", status_code=400)

        with pytest.raises(LLMProviderError):
            call_with_retry(
                op,
                policy=RetryPolicy(max_attempts=5, base_delay_seconds=0.0),
                state=state,
            )
        assert state.retries == 0
        assert calls["n"] == 1
