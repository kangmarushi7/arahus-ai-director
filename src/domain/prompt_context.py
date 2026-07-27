"""Prompt-facing domain context loaded from YAML configuration files."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from src.domain.models import DomainType
from src.models.base import StrictModel


class DomainPromptContext(StrictModel):
    """Visual and prompt defaults for a single content domain.

    Sourced from YAML under ``src/domain/configs/``. Prompt agents should consume
    this model rather than hardcoding style language in Python.
    """

    domain: DomainType
    style: str
    camera: str
    lighting: str
    composition: str
    quality_tags: list[str] = Field(default_factory=list)
    negative_prompt: str
    image_defaults: dict[str, Any] = Field(default_factory=dict)
    video_defaults: dict[str, Any] = Field(default_factory=dict)
    # Present in YAML schema; kept on the context for prompt builders.
    color_palette: str = ""

    @field_validator(
        "style",
        "camera",
        "lighting",
        "composition",
        "negative_prompt",
        "color_palette",
        mode="before",
    )
    @classmethod
    def _normalize_multiline(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("quality_tags", mode="before")
    @classmethod
    def _normalize_quality_tags(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [part for part in parts if part]
        return value
