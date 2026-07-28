"""Task-based LLM router."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from src.llm.config import LLMRouterConfig, ProviderConfig, load_router_config
from src.llm.exceptions import LLMConfigError, LLMProviderError, LLMRoutingError
from src.llm.metrics import LLMMetrics
from src.llm.models import ChatMessage, LLMResponse
from src.llm.pricing import PricingTable
from src.llm.providers.base import LLMProvider
from src.llm.providers.openrouter import OpenRouterProvider
from src.llm.retry import RetryPolicy, RetryState, call_with_retry

logger = logging.getLogger(__name__)


class LLMRouter:
    """Route logical tasks to configured providers and models."""

    def __init__(
        self,
        config: LLMRouterConfig,
        *,
        providers: Mapping[str, LLMProvider] | None = None,
        metrics: LLMMetrics | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics or LLMMetrics()
        self._providers: dict[str, LLMProvider] = (
            dict(providers) if providers is not None else self._build_providers(config)
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | None = None,
        *,
        metrics: LLMMetrics | None = None,
    ) -> LLMRouter:
        """Construct a router from packaged or custom YAML."""
        return cls(load_router_config(path), metrics=metrics)

    @property
    def config(self) -> LLMRouterConfig:
        return self._config

    @property
    def metrics(self) -> LLMMetrics:
        return self._metrics

    @property
    def pricing(self) -> PricingTable:
        return self._config.pricing

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._config.retry

    def generate(
        self,
        *,
        task: str,
        messages: Sequence[ChatMessage] | Sequence[Mapping[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> LLMResponse:
        """Route ``task`` and execute a chat completion."""
        route = self._config.route_for(task)
        provider_name = (provider or route.provider).strip()
        model_name = (model or route.model).strip()
        temp = route.temperature if temperature is None else float(temperature)
        tokens = route.max_tokens if max_tokens is None else int(max_tokens)

        try:
            backend = self._providers[provider_name]
        except KeyError as exc:
            raise LLMRoutingError(
                f"No provider registered for {provider_name!r}"
            ) from exc

        normalized = _normalize_messages(messages)
        started = time.perf_counter()
        logger.info(
            "event=llm_request_start task=%s provider=%s model=%s "
            "messages=%s temperature=%.3f max_tokens=%s",
            route.task,
            provider_name,
            model_name,
            len(normalized),
            temp,
            tokens,
        )

        retry_state = RetryState()
        try:
            completion = call_with_retry(
                lambda: backend.complete(
                    model=model_name,
                    messages=normalized,
                    temperature=temp,
                    max_tokens=tokens,
                    response_format=response_format,
                ),
                policy=self._config.retry,
                operation_name=f"{provider_name}:{model_name}",
                state=retry_state,
            )
        except LLMProviderError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._metrics.record_failure(
                task=route.task,
                model=model_name,
                latency_ms=latency_ms,
            )
            _record_cost_tracker_call(
                task=route.task,
                provider=provider_name,
                model=model_name,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                estimated_cost=0.0,
                retries=retry_state.retries,
                success=False,
            )
            _record_audit_exchange(
                task=route.task,
                messages=normalized,
                response_text=None,
                provider=provider_name,
                model=model_name,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.0,
                success=False,
                error=str(exc),
                meta={"retries": retry_state.retries},
            )
            logger.error(
                "event=llm_request_failed task=%s provider=%s model=%s "
                "latency_ms=%.1f retries=%s error=%s",
                route.task,
                provider_name,
                model_name,
                latency_ms,
                retry_state.retries,
                exc,
            )
            raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        cost = self._config.pricing.estimate(
            completion.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
        response = LLMResponse(
            text=completion.text,
            provider=provider_name,
            model=completion.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            latency_ms=round(latency_ms, 3),
            estimated_cost=cost,
            finish_reason=completion.finish_reason,
            raw=dict(completion.raw),
            task=route.task,
        )
        self._metrics.record(response)
        _record_cost_tracker_call(
            task=response.task or route.task,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            estimated_cost=response.estimated_cost,
            retries=retry_state.retries,
            success=True,
        )
        _record_audit_exchange(
            task=response.task or route.task,
            messages=normalized,
            response_text=response.text,
            provider=response.provider,
            model=response.model,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost=response.estimated_cost,
            success=True,
            meta={
                "retries": retry_state.retries,
                "finish_reason": response.finish_reason,
            },
        )
        logger.info(
            "event=llm_request_complete task=%s provider=%s model=%s "
            "input_tokens=%s output_tokens=%s latency_ms=%.1f "
            "estimated_cost=%.8f retries=%s finish_reason=%s",
            response.task,
            response.provider,
            response.model,
            response.input_tokens,
            response.output_tokens,
            response.latency_ms,
            response.estimated_cost,
            retry_state.retries,
            response.finish_reason,
        )
        return response

    @staticmethod
    def _build_providers(config: LLMRouterConfig) -> dict[str, LLMProvider]:
        providers: dict[str, LLMProvider] = {}
        for name, provider_cfg in config.providers.items():
            providers[name] = _build_provider(provider_cfg)
        return providers


def _record_cost_tracker_call(
    *,
    task: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    estimated_cost: float,
    retries: int,
    success: bool,
) -> None:
    """Push one LLM call into the bound pipeline :class:`CostTracker`, if any."""
    # Lazy import avoids a circular dependency: llm.router ↔ monitoring.
    from src.monitoring.cost_tracker import get_cost_tracker

    tracker = get_cost_tracker()
    if tracker is None:
        return
    tracker.record_llm_call(
        task=task,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        estimated_cost=estimated_cost,
        retries=retries,
        success=success,
    )


def _record_audit_exchange(
    *,
    task: str,
    messages: Sequence[Any],
    response_text: str | None,
    provider: str,
    model: str,
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
    success: bool,
    error: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> None:
    """Append request/response text to the bound pipeline audit run, if any."""
    # Lazy import avoids a circular dependency: llm.router ↔ audit.
    from src.audit.store import messages_to_prompt_text, record_llm_exchange

    record_llm_exchange(
        tag=task,
        request=messages_to_prompt_text(messages),
        response=response_text,
        model=model,
        provider=provider,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
        success=success,
        error=error,
        meta=dict(meta or {}),
    )


def _build_provider(cfg: ProviderConfig) -> LLMProvider:
    if cfg.type == "openrouter":
        return OpenRouterProvider(
            api_key=cfg.resolve_api_key(),
            base_url=cfg.base_url,
            timeout_seconds=cfg.timeout_seconds,
            default_headers=cfg.default_headers,
            name=cfg.name,
        )
    raise LLMConfigError(f"Unsupported provider type {cfg.type!r}")


def _normalize_messages(
    messages: Sequence[ChatMessage] | Sequence[Mapping[str, str]],
) -> list[ChatMessage]:
    if not messages:
        raise ValueError("messages must be a non-empty sequence")
    normalized: list[ChatMessage] = []
    for item in messages:
        if isinstance(item, ChatMessage):
            normalized.append(item)
            continue
        if isinstance(item, Mapping):
            normalized.append(
                ChatMessage(
                    role=str(item.get("role") or "user"),  # type: ignore[arg-type]
                    content=str(item.get("content") or ""),
                )
            )
            continue
        raise TypeError(
            "messages must contain ChatMessage or mapping values, "
            f"got {type(item).__name__}"
        )
    return normalized
