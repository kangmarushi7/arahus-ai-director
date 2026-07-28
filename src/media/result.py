"""Shared result / metrics contracts for media engines."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.media.request import GenerationProfileName, QualityMode
from src.models.base import StrictModel
from src.models.image import ImageResult, VideoResult

__all__ = [
    "ImageResult",
    "MediaGenerationMetrics",
    "VideoResult",
]


class MediaGenerationMetrics(StrictModel):
    """Common observability fields for any media generation attempt."""

    provider: str
    model: str
    runtime_ms: float = Field(ge=0.0, default=0.0)
    gpu_seconds: float = Field(ge=0.0, default=0.0)
    estimated_cost: float = Field(ge=0.0, default=0.0)
    resolution: str = ""
    quality: QualityMode = "production"
    profile: GenerationProfileName = "production"
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
