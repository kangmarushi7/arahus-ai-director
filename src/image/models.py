"""Public models for the provider-agnostic image engine."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from src.models.base import StrictModel
from src.models.image import ImageResult

QualityMode = Literal["preview", "production", "experimental"]
GenerationProfileName = Literal["preview", "production", "cinematic"]


class ImageRequest(StrictModel):
    """Input to :meth:`~src.image.router.ImageRouter.generate`."""

    prompt: str
    quality: QualityMode = "production"
    profile: GenerationProfileName | None = None
    model: str | None = None
    provider: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
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


class GenerationParams(StrictModel):
    """Resolved generation parameters after profile / model merging."""

    model_key: str
    model_id: str
    provider: str
    quality: QualityMode
    profile: GenerationProfileName
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    steps: int = Field(ge=1, default=28)
    guidance_scale: float = Field(ge=0.0, default=3.5)
    cost_per_image: float = Field(ge=0.0, default=0.0)
    extras: dict[str, Any] = Field(default_factory=dict)

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


class ImageGenerationMetrics(StrictModel):
    """Per-generation observability snapshot."""

    provider: str
    model: str
    runtime_ms: float = Field(ge=0.0, default=0.0)
    estimated_cost: float = Field(ge=0.0, default=0.0)
    resolution: str = ""
    quality: QualityMode = "production"
    profile: GenerationProfileName = "production"
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ImageGenerationResult(StrictModel):
    """Structured result from :meth:`~src.image.router.ImageRouter.generate`."""

    prompt: str
    image: ImageResult
    params: GenerationParams
    metrics: ImageGenerationMetrics

    @property
    def url(self) -> str | None:
        return self.image.url

    def to_image_result(self) -> ImageResult:
        """Return the pipeline-compatible :class:`ImageResult`."""
        return self.image
