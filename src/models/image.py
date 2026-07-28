"""The output of the video-generation stage."""

from __future__ import annotations

from pydantic import Field

from src.models.base import StrictModel


class ImageResult(StrictModel):
    """The output of the image-generation stage for one scene."""

    prompt: str
    url: str | None = None
    b64: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    seed: int | None = None


class VideoResult(StrictModel):
    """The output of the video-generation stage."""

    prompt: str = ""
    url: str | None = None
    b64: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    fps: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    seed: int | None = None
    source_image: str | None = None
    source_image_urls: list[str] = Field(default_factory=list)
    asset_id: int | None = Field(default=None, ge=1)
