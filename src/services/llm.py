"""Compatibility LLM client that returns validated Pydantic models.

Agents continue to call :meth:`LLMClient.generate_json`. Internally this client
routes through :class:`~src.llm.client.LLM` (``llm.generate(task=..., ...)``)
so OpenRouter details stay behind the provider abstraction.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.cache.llm_cache import LLMCache
from src.config import get_settings
from src.llm import LLM, LLMProviderError, LLMResponse, get_llm
from src.llm.exceptions import LLMError

T = TypeVar("T", bound=BaseModel)

_CACHEABLE_TASKS = frozenset({"domain"})
_shared_cache: LLMCache | None = None
_shared_cache_lock = threading.Lock()


def _task_cache() -> LLMCache | None:
    """Return the shared LLM cache when enabled for cacheable tasks."""
    global _shared_cache
    if not get_settings().pipeline.llm_cache_enabled:
        return None
    with _shared_cache_lock:
        if _shared_cache is None:
            _shared_cache = LLMCache()
        return _shared_cache


_FENCE_RE = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$",
    re.DOTALL | re.IGNORECASE,
)

_JSON_SYSTEM = (
    "You are a careful assistant that returns only valid JSON matching the "
    "user's schema. Never wrap the JSON in markdown."
)


class LLMClientError(Exception):
    """Base error for failures inside :class:`LLMClient`."""


class LLMRequestError(LLMClientError):
    """Raised when the underlying provider request fails."""


class LLMJSONParseError(LLMClientError):
    """Raised when the model response cannot be parsed as JSON."""

    def __init__(self, message: str, *, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class LLMValidationError(LLMClientError):
    """Raised when parsed JSON fails Pydantic validation."""

    def __init__(
        self,
        message: str,
        *,
        raw_text: str,
        data: object | None,
        cause: ValidationError,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.data = data
        self.cause = cause


class LLMClient:
    """Agent-facing client: prompt → validated Pydantic model via LLM router."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4000,
        *,
        task: str = "general",
        llm: LLM | None = None,
    ) -> None:
        """Configure the compatibility client.

        ``api_key`` / ``base_url`` are accepted for backwards compatibility but
        routing/credentials come from the injected :class:`~src.llm.client.LLM`
        (YAML + env). ``model`` overrides the task's configured model when set.
        """
        if max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")

        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = (model or "").strip()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.task = task.strip().lower()
        self._llm = llm
        self.progress_callback: Callable[[str], None] | None = None
        self._logger = logging.getLogger(self.__class__.__name__)
        self.last_response: LLMResponse | None = None

    def _resolve_llm(self) -> LLM:
        return self._llm if self._llm is not None else get_llm()

    def _log_progress(self, message: str) -> None:
        if self.progress_callback is not None:
            try:
                self.progress_callback(message)
            except Exception:  # noqa: BLE001
                self._logger.exception("progress_callback failed")

    def generate_json(self, prompt: str, response_model: Type[T]) -> T:
        """Send ``prompt`` through the LLM router and validate JSON."""
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        model_label = self.model or self.task
        cache = _task_cache() if self.task in _CACHEABLE_TASKS else None
        cache_model = self.model or f"task:{self.task}"
        if cache is not None:
            cached = cache.get(cache_model, self.temperature, prompt)
            if cached is not None:
                self._log_progress(
                    f"LLM [{model_label}] cache hit → {response_model.__name__}"
                )
                from src.audit.store import record_llm_exchange

                record_llm_exchange(
                    tag=self.task,
                    request=prompt,
                    response=json.dumps(cached, ensure_ascii=False),
                    model=cache_model,
                    provider="cache",
                    latency_ms=0.0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost=0.0,
                    success=True,
                    meta={"cache_hit": True, "response_model": response_model.__name__},
                )
                return self._validate(cached, response_model, raw_text=json.dumps(cached))

        self._log_progress(
            f"LLM [{model_label}] sending request "
            f"({len(prompt)} chars → {response_model.__name__})"
        )
        started = time.perf_counter()
        try:
            response = self._resolve_llm().generate(
                task=self.task,
                messages=[
                    {"role": "system", "content": _JSON_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                model=self.model or None,
            )
        except LLMProviderError as exc:
            raise LLMRequestError(
                f"LLM request failed for task '{self.task}' model "
                f"'{self.model or 'route-default'}': {exc}"
            ) from exc
        except LLMError as exc:
            raise LLMRequestError(
                f"LLM router error for task '{self.task}': {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMRequestError(
                f"Unexpected LLM client error for task '{self.task}': {exc}"
            ) from exc

        self.last_response = response
        raw_text = response.text
        self._log_progress(
            f"LLM [{response.model}] response received "
            f"({len(raw_text)} chars in {time.perf_counter() - started:.1f}s, "
            f"cost≈{response.estimated_cost:.6f})"
        )

        self._log_progress(f"LLM [{response.model}] parsing JSON…")
        data = self._parse_json(raw_text)
        self._log_progress(f"LLM [{response.model}] validating {response_model.__name__}…")
        result = self._validate(data, response_model, raw_text=raw_text)
        if cache is not None:
            try:
                cache.set(
                    cache_model,
                    self.temperature,
                    prompt,
                    result.model_dump(mode="json"),
                )
            except Exception:  # noqa: BLE001
                self._logger.exception("event=llm_cache_set_failed task=%s", self.task)
        self._log_progress(f"LLM [{response.model}] validated {response_model.__name__} OK")
        return result

    def _parse_json(self, raw_text: str) -> object:
        candidate = raw_text.strip()
        fence_match = _FENCE_RE.match(candidate)
        if fence_match:
            candidate = fence_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            preview = candidate[:500]
            raise LLMJSONParseError(
                f"Failed to parse LLM response as JSON: {exc}. Preview: {preview!r}",
                raw_text=raw_text,
            ) from exc

    def _validate(
        self,
        data: object,
        response_model: Type[T],
        *,
        raw_text: str,
    ) -> T:
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMValidationError(
                f"LLM JSON failed validation for {response_model.__name__}: {exc}",
                raw_text=raw_text,
                data=data,
                cause=exc,
            ) from exc
