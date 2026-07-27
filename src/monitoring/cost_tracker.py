"""Per-run LLM cost and token tracking."""

from __future__ import annotations

import threading
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from typing import Any

from src.llm.models import LLMResponse

_current_tracker: ContextVar[CostTracker | None] = ContextVar(
    "pipeline_cost_tracker",
    default=None,
)


@dataclass(slots=True)
class LLMCallRecord:
    """One LLM router invocation attributed to a pipeline run."""

    task: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost: float = 0.0
    retries: int = 0
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostTracker:
    """Thread-safe accumulator for LLM calls within one pipeline run."""

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _calls: list[LLMCallRecord] = field(default_factory=list)
    _extra_retries: int = 0

    def record_llm_call(
        self,
        *,
        task: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        estimated_cost: float = 0.0,
        retries: int = 0,
        success: bool = True,
    ) -> LLMCallRecord:
        """Record one LLM call and return the stored record."""
        record = LLMCallRecord(
            task=(task or "unknown").strip().lower(),
            provider=provider or "unknown",
            model=model or "unknown",
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
            latency_ms=max(0.0, float(latency_ms)),
            estimated_cost=max(0.0, float(estimated_cost)),
            retries=max(0, int(retries)),
            success=bool(success),
        )
        with self._lock:
            self._calls.append(record)
        return record

    def record_response(
        self,
        response: LLMResponse,
        *,
        retries: int = 0,
        success: bool = True,
    ) -> LLMCallRecord:
        """Record from a structured :class:`LLMResponse`."""
        return self.record_llm_call(
            task=response.task or "unknown",
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            estimated_cost=response.estimated_cost,
            retries=retries,
            success=success,
        )

    def record_retry(self, count: int = 1) -> None:
        """Record non-LLM retries (e.g. storyboard regeneration)."""
        if count < 0:
            raise ValueError("retry count must be non-negative")
        with self._lock:
            self._extra_retries += int(count)

    @property
    def calls(self) -> list[LLMCallRecord]:
        with self._lock:
            return list(self._calls)

    @property
    def total_input_tokens(self) -> int:
        with self._lock:
            return sum(call.input_tokens for call in self._calls)

    @property
    def total_output_tokens(self) -> int:
        with self._lock:
            return sum(call.output_tokens for call in self._calls)

    @property
    def total_llm_cost(self) -> float:
        with self._lock:
            return sum(call.estimated_cost for call in self._calls)

    @property
    def total_retries(self) -> int:
        with self._lock:
            return self._extra_retries + sum(call.retries for call in self._calls)

    def cost_by_task(self) -> dict[str, float]:
        with self._lock:
            totals: dict[str, float] = {}
            for call in self._calls:
                totals[call.task] = totals.get(call.task, 0.0) + call.estimated_cost
            return totals

    def tokens_by_task(self) -> dict[str, tuple[int, int]]:
        with self._lock:
            totals: dict[str, tuple[int, int]] = {}
            for call in self._calls:
                inp, out = totals.get(call.task, (0, 0))
                totals[call.task] = (inp + call.input_tokens, out + call.output_tokens)
            return totals

    def retries_by_task(self) -> dict[str, int]:
        with self._lock:
            totals: dict[str, int] = {}
            for call in self._calls:
                totals[call.task] = totals.get(call.task, 0) + call.retries
            return totals

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._extra_retries = 0

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": [call.to_dict() for call in self._calls],
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_llm_cost": round(self.total_llm_cost, 8),
                "total_retries": self.total_retries,
                "cost_by_task": {
                    key: round(value, 8) for key, value in self.cost_by_task().items()
                },
            }


def get_cost_tracker() -> CostTracker | None:
    """Return the cost tracker bound to the current context, if any."""
    return _current_tracker.get()


def bind_cost_tracker(tracker: CostTracker) -> Token[CostTracker | None]:
    """Bind ``tracker`` to the current context; return a reset token."""
    return _current_tracker.set(tracker)


def reset_cost_tracker(token: Token[CostTracker | None]) -> None:
    """Restore the previous cost-tracker binding."""
    _current_tracker.reset(token)
