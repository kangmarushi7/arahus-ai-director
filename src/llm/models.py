"""Pydantic models for the LLM router."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from src.models.base import StrictModel

ChatRole = Literal["system", "user", "assistant", "tool"]


class ChatMessage(StrictModel):
    """One chat message sent to a provider."""

    role: ChatRole
    content: str

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class LLMResponse(StrictModel):
    """Structured result from :meth:`~src.llm.client.LLM.generate`."""

    text: str
    provider: str
    model: str
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    latency_ms: float = Field(ge=0.0, default=0.0)
    estimated_cost: float = Field(ge=0.0, default=0.0)
    finish_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    task: str | None = None

    @field_validator("text", "provider", "model", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ProviderCompletion(StrictModel):
    """Low-level provider completion before pricing / metrics enrichment."""

    text: str
    model: str
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    finish_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
