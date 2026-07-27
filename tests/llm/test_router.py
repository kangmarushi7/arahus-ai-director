"""Unit tests for the LLM router stack."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src.llm import (
    LLM,
    LLMConfigError,
    LLMMetrics,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMRouter,
    LLMTimeoutError,
    ModelPrice,
    OpenRouterProvider,
    PricingTable,
    ProviderCompletion,
    RetryPolicy,
    call_with_retry,
    is_retriable,
    parse_router_config,
    reset_llm_singleton,
)
from src.llm.config import load_router_config
from src.llm.models import ChatMessage
from src.services.llm import LLMClient, LLMRequestError


class _FakeProvider:
    def __init__(
        self,
        *,
        name: str = "fake",
        text: str = '{"ok": true}',
        fail_times: int = 0,
        error_factory: Any = None,
    ) -> None:
        self.name = name
        self.text = text
        self.fail_times = fail_times
        self.error_factory = error_factory or (
            lambda: LLMRateLimitError("rate limited", provider=name, model="m")
        )
        self.calls = 0

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        temperature: float,
        max_tokens: int,
        response_format: Mapping[str, Any] | None = None,
    ) -> ProviderCompletion:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error_factory()
        return ProviderCompletion(
            text=self.text,
            model=model,
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
            raw={"id": "fake-1"},
        )


def _sample_config_dict() -> dict[str, Any]:
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
        "retry": {
            "max_attempts": 3,
            "base_delay_seconds": 0.0,
            "max_delay_seconds": 0.0,
            "jitter_ratio": 0.0,
        },
        "tasks": {
            "research": {
                "provider": "openrouter",
                "model": "test/model-a",
                "temperature": 0.1,
                "max_tokens": 100,
            },
            "director": {
                "provider": "openrouter",
                "model": "test/model-b",
                "temperature": 0.2,
                "max_tokens": 200,
            },
            "general": {
                "provider": "openrouter",
                "model": "test/model-a",
            },
        },
        "pricing": {
            "default": {"input_per_million": 1.0, "output_per_million": 2.0},
            "test/model-a": {"input_per_million": 0.0, "output_per_million": 0.0},
        },
    }


class TestConfig:
    def test_load_packaged_yaml(self) -> None:
        cfg = load_router_config()
        assert "research" in cfg.tasks
        assert "openrouter" in cfg.providers
        assert cfg.route_for("prompt").model

    def test_unknown_task_raises(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        with pytest.raises(LLMConfigError, match="Unknown LLM task"):
            cfg.route_for("missing")

    def test_invalid_provider_type_in_build(self) -> None:
        raw = _sample_config_dict()
        raw["providers"]["openrouter"]["type"] = "nope"
        cfg = parse_router_config(raw)
        with pytest.raises(LLMConfigError, match="Unsupported provider type"):
            LLMRouter(cfg)


class TestPricing:
    def test_estimate_cost(self) -> None:
        table = PricingTable(
            {"m": ModelPrice(input_per_million=1.0, output_per_million=2.0)}
        )
        cost = table.estimate("m", input_tokens=1_000_000, output_tokens=500_000)
        assert cost == pytest.approx(2.0)

    def test_free_suffix_fallback(self) -> None:
        table = PricingTable(
            {"acme/model": ModelPrice(input_per_million=3.0, output_per_million=0.0)},
            default=ModelPrice(input_per_million=9.0, output_per_million=9.0),
        )
        assert table.get("acme/model:free").input_per_million == 3.0


class TestRetry:
    def test_retries_rate_limit_then_succeeds(self) -> None:
        calls = {"n": 0}

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
        )
        assert result == "ok"
        assert calls["n"] == 3

    def test_non_retriable_raises_immediately(self) -> None:
        calls = {"n": 0}

        def op() -> str:
            calls["n"] += 1
            raise LLMProviderError("nope", provider="x", model="y", status_code=400)

        with pytest.raises(LLMProviderError):
            call_with_retry(
                op,
                policy=RetryPolicy(max_attempts=5, base_delay_seconds=0.0),
            )
        assert calls["n"] == 1

    def test_is_retriable_matrix(self) -> None:
        assert is_retriable(LLMTimeoutError("t", provider="p", model="m"))
        assert is_retriable(LLMRateLimitError("r", provider="p", model="m"))
        assert is_retriable(
            LLMProviderError("5xx", provider="p", model="m", status_code=503)
        )
        assert not is_retriable(
            LLMProviderError("4xx", provider="p", model="m", status_code=400)
        )


class TestRouterGenerate:
    def test_generate_routes_by_task_and_records_metrics(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text="hello world")
        metrics = LLMMetrics()
        router = LLMRouter(cfg, providers={"openrouter": provider}, metrics=metrics)

        response = router.generate(
            task="research",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert isinstance(response, LLMResponse)
        assert response.text == "hello world"
        assert response.provider == "openrouter"
        assert response.model == "test/model-a"
        assert response.task == "research"
        assert response.input_tokens == 10
        assert response.output_tokens == 5
        assert response.estimated_cost == 0.0
        assert response.latency_ms >= 0.0
        snap = metrics.snapshot()
        assert snap["by_task"]["research"]["requests"] == 1

    def test_public_llm_generate(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text="from llm")
        llm = LLM(LLMRouter(cfg, providers={"openrouter": provider}))
        response = llm.generate(
            task="director",
            messages=[ChatMessage(role="user", content="plan")],
        )
        assert response.model == "test/model-b"
        assert response.text == "from llm"

    def test_retries_inside_router(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text="recovered", fail_times=2)
        router = LLMRouter(cfg, providers={"openrouter": provider})
        response = router.generate(
            task="general",
            messages=[{"role": "user", "content": "x"}],
        )
        assert response.text == "recovered"
        assert provider.calls == 3


class TestOpenRouterProvider:
    def test_maps_rate_limit(self) -> None:
        from openai import RateLimitError

        client = MagicMock()
        err = RateLimitError(
            message="rate",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client.chat.completions.create.side_effect = err
        provider = OpenRouterProvider(
            api_key="test-key",
            client=client,
        )
        with pytest.raises(LLMRateLimitError):
            provider.complete(
                model="m",
                messages=[ChatMessage(role="user", content="hi")],
                temperature=0.2,
                max_tokens=10,
            )

    def test_success_parses_usage(self) -> None:
        client = MagicMock()
        message = MagicMock()
        message.content = "  hello  "
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        completion = MagicMock()
        completion.choices = [choice]
        completion.usage = MagicMock(prompt_tokens=3, completion_tokens=7, total_tokens=10)
        completion.id = "abc"
        client.chat.completions.create.return_value = completion

        provider = OpenRouterProvider(api_key="test-key", client=client)
        result = provider.complete(
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.1,
            max_tokens=16,
            response_format={"type": "json_object"},
        )
        assert result.text == "hello"
        assert result.input_tokens == 3
        assert result.output_tokens == 7
        assert result.finish_reason == "stop"


class _TinyModel(BaseModel):
    ok: bool


class TestCompatibilityClient:
    def test_generate_json_uses_router(self) -> None:
        reset_llm_singleton()
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(text=json.dumps({"ok": True}))
        llm = LLM(LLMRouter(cfg, providers={"openrouter": provider}))
        client = LLMClient(
            model="test/model-a",
            task="research",
            temperature=0.1,
            max_tokens=50,
            llm=llm,
        )
        result = client.generate_json("return json", _TinyModel)
        assert result.ok is True
        assert client.last_response is not None
        assert client.last_response.task == "research"

    def test_generate_json_maps_provider_errors(self) -> None:
        cfg = parse_router_config(_sample_config_dict())
        provider = _FakeProvider(
            fail_times=99,
            error_factory=lambda: LLMProviderError(
                "boom", provider="openrouter", model="m", status_code=400
            ),
        )
        # max_attempts 1 via config retry already 3 - non-retriable 400 fails once
        llm = LLM(LLMRouter(cfg, providers={"openrouter": provider}))
        client = LLMClient(task="general", llm=llm, model="test/model-a")
        with pytest.raises(LLMRequestError):
            client.generate_json("x", _TinyModel)
