"""Public models for the provider-agnostic video engine."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from src.media.request import GenerationProfileName, MediaRequest, QualityMode
from src.media.result import MediaGenerationMetrics
from src.models.base import StrictModel
from src.models.image import VideoResult

VideoMode = Literal["text-to-video", "image-to-video"]


class VideoRequest(MediaRequest):
    """Input to :meth:`~src.video.router.VideoRouter.generate`.

    Supports text-to-video (prompt only) and image-to-video (``source_image``
    or ``source_image_urls``). Future video-to-video can add optional fields
    without breaking this shape.
    """

    source_image: str | None = None
    source_image_urls: list[str] = Field(default_factory=list)
    duration: float | None = Field(default=None, ge=0.1)
    aspect_ratio: str | None = None
    fps: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    motion: str | None = None

    @field_validator("source_image", "aspect_ratio", "motion", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split()) or None
        return value

    @field_validator("source_image_urls", mode="before")
    @classmethod
    def _normalize_urls(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @model_validator(mode="after")
    def _sync_source_images(self) -> VideoRequest:
        urls = list(self.source_image_urls)
        if self.source_image and self.source_image not in urls:
            urls = [self.source_image, *urls]
        if urls and not self.source_image:
            object.__setattr__(self, "source_image", urls[0])
        object.__setattr__(self, "source_image_urls", urls)
        return self

    @property
    def mode(self) -> VideoMode:
        if self.source_image or self.source_image_urls:
            return "image-to-video"
        return "text-to-video"


class VideoGenerationParams(StrictModel):
    """Resolved generation parameters after profile / model merging."""

    model_key: str
    model_id: str
    provider: str
    quality: QualityMode
    profile: GenerationProfileName
    mode: VideoMode
    duration: float = Field(ge=0.1, default=5.0)
    fps: int = Field(ge=1, default=24)
    width: int = Field(ge=1, default=720)
    height: int = Field(ge=1, default=1280)
    aspect_ratio: str = "9:16"
    motion: str = ""
    cost_per_second: float = Field(ge=0.0, default=0.0)
    extras: dict[str, Any] = Field(default_factory=dict)

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def estimated_cost(self) -> float:
        return round(self.cost_per_second * self.duration, 8)


class VideoGenerationMetrics(MediaGenerationMetrics):
    """Per-generation observability snapshot for video."""

    duration: float = Field(ge=0.0, default=0.0)
    fps: int = Field(ge=0, default=0)
    mode: VideoMode = "text-to-video"

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        # Alias runtime seconds for dashboard consumers.
        payload["runtime"] = round(self.runtime_ms / 1000.0, 3)
        payload["cost"] = self.estimated_cost
        return payload


class VideoGenerationResult(StrictModel):
    """Structured result from :meth:`~src.video.router.VideoRouter.generate`."""

    prompt: str
    video: VideoResult
    params: VideoGenerationParams
    metrics: VideoGenerationMetrics
    request_mode: VideoMode = "text-to-video"

    @property
    def url(self) -> str | None:
        return self.video.url

    def to_video_result(self) -> VideoResult:
        """Return the pipeline-compatible :class:`VideoResult`."""
        return self.video
