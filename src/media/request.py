"""Shared request fields for media engines."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from src.models.base import StrictModel

QualityMode = Literal["preview", "production", "experimental"]
GenerationProfileName = Literal["preview", "production", "cinematic"]


class MediaRequest(StrictModel):
    """Common input fields shared by image / video / future media routers.

    Modality-specific engines extend this model (e.g. :class:`VideoRequest`
    adds ``source_image``, ``duration``, ``fps``).
    """

    prompt: str
    quality: QualityMode = "production"
    profile: GenerationProfileName | None = None
    model: str | None = None
    provider: str | None = None
    seed: int | None = None
    negative_prompt: str | None = None

    @field_validator("prompt", mode="before")
    @classmethod
    def _require_prompt(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            if not cleaned:
                raise ValueError("prompt must be a non-empty string")
            return cleaned
        return value
