"""OpenRouter (OpenAI-compatible) provider implementation."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from src.llm.exceptions import LLMProviderError, LLMRateLimitError, LLMTimeoutError
from src.llm.models import ChatMessage, ProviderCompletion

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """Encapsulates all OpenRouter-specific transport details."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 120.0,
        default_headers: Mapping[str, str] | None = None,
        name: str = "openrouter",
        client: OpenAI | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")

        self._name = name.strip() or "openrouter"
        self._model_default_headers = dict(default_headers or {})
        self._client = client or OpenAI(
            api_key=api_key.strip(),
            base_url=base_url.strip().rstrip("/"),
            timeout=timeout_seconds,
            default_headers=dict(self._model_default_headers) or None,
        )

    @property
    def name(self) -> str:
        return self._name

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        temperature: float,
        max_tokens: int,
        response_format: Mapping[str, Any] | None = None,
    ) -> ProviderCompletion:
        """Call OpenRouter chat completions and normalize the response."""
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if not messages:
            raise ValueError("messages must be a non-empty sequence")
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")

        payload_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        kwargs: dict[str, Any] = {
            "model": model.strip(),
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = dict(response_format)

        try:
            completion = self._client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            raise LLMRateLimitError(
                f"OpenRouter rate limited for model {model!r}: {exc}",
                provider=self.name,
                model=model,
            ) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError(
                f"OpenRouter timed out for model {model!r}: {exc}",
                provider=self.name,
                model=model,
            ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                f"OpenRouter connection error for model {model!r}: {exc}",
                provider=self.name,
                model=model,
                retriable=True,
            ) from exc
        except APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            retriable = bool(status == 429 or (isinstance(status, int) and status >= 500))
            if status == 429:
                raise LLMRateLimitError(
                    f"OpenRouter HTTP 429 for model {model!r}: {exc}",
                    provider=self.name,
                    model=model,
                ) from exc
            raise LLMProviderError(
                f"OpenRouter HTTP {status} for model {model!r}: {exc}",
                provider=self.name,
                model=model,
                status_code=status if isinstance(status, int) else None,
                retriable=retriable,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - isolate SDK quirks
            raise LLMProviderError(
                f"Unexpected OpenRouter error for model {model!r}: {exc}",
                provider=self.name,
                model=model,
                retriable=False,
            ) from exc

        try:
            choice = completion.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, "finish_reason", None)
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "OpenRouter response missing message content",
                provider=self.name,
                model=model,
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError(
                "OpenRouter returned an empty response",
                provider=self.name,
                model=model,
            )

        usage = getattr(completion, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        raw: dict[str, Any] = {
            "id": getattr(completion, "id", None),
            "finish_reason": finish_reason,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            },
        }
        logger.debug(
            "event=openrouter_complete model=%s input_tokens=%s output_tokens=%s",
            model,
            input_tokens,
            output_tokens,
        )
        return ProviderCompletion(
            text=content.strip(),
            model=model.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=str(finish_reason) if finish_reason else None,
            raw=raw,
        )
