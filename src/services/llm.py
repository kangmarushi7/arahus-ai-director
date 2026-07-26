"""OpenAI-compatible LLM client that returns validated Pydantic models."""

from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# Matches ```json ... ``` or ``` ... ``` fences LLMs occasionally wrap around JSON.
_FENCE_RE = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$",
    re.DOTALL | re.IGNORECASE,
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
    """Thin client that turns a prompt into a validated Pydantic model.

    Provider transport details (OpenAI-compatible chat completions) stay inside
    this class so agents only depend on :meth:`generate_json`. Model, sampling,
    and endpoint settings are injected — never hardcoded.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        """Configure the OpenAI-compatible client.

        Args:
            api_key: Provider API key.
            base_url: Provider base URL, e.g. OpenRouter's ``/api/v1``.
            model: Model identifier, e.g. ``openai/gpt-oss-20b:free``.
            temperature: Sampling temperature for every request.
            max_tokens: Maximum completion tokens for every request.
        """
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")

        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate_json(self, prompt: str, response_model: Type[T]) -> T:
        """Send ``prompt`` to the LLM and return a validated ``response_model``.

        Args:
            prompt: Instruction text for the model.
            response_model: Pydantic model class used for validation.

        Returns:
            An instance of ``response_model``.

        Raises:
            ValueError: If ``prompt`` is empty.
            LLMRequestError: If the provider request fails.
            LLMJSONParseError: If the response is not valid JSON.
            LLMValidationError: If JSON does not match ``response_model``.
        """
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        raw_text = self._request_json_text(prompt)
        data = self._parse_json(raw_text)
        return self._validate(data, response_model, raw_text=raw_text)

    def _request_json_text(self, prompt: str) -> str:
        """Call the provider and return the assistant message content."""
        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a careful assistant that returns only "
                            "valid JSON matching the user's schema. "
                            "Never wrap the JSON in markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except (APIError, APITimeoutError, RateLimitError) as exc:
            raise LLMRequestError(
                f"LLM request failed for model '{self.model}': {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - isolate provider SDK quirks
            raise LLMRequestError(
                f"Unexpected LLM client error for model '{self.model}': {exc}"
            ) from exc

        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMRequestError(
                "LLM response did not include message content"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError("LLM returned an empty response")

        return content.strip()

    def _parse_json(self, raw_text: str) -> object:
        """Parse JSON, stripping accidental markdown fences if present."""
        candidate = raw_text.strip()
        fence_match = _FENCE_RE.match(candidate)
        if fence_match:
            candidate = fence_match.group(1).strip()

        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            preview = candidate[:500]
            raise LLMJSONParseError(
                f"Failed to parse LLM response as JSON: {exc}. "
                f"Preview: {preview!r}",
                raw_text=raw_text,
            ) from exc

    def _validate(
        self,
        data: object,
        response_model: Type[T],
        *,
        raw_text: str,
    ) -> T:
        """Validate parsed data against ``response_model``."""
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMValidationError(
                f"LLM JSON failed validation for "
                f"{response_model.__name__}: {exc}",
                raw_text=raw_text,
                data=data,
                cause=exc,
            ) from exc
