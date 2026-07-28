"""Image provider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.image.models import GenerationParams
from src.models.image import ImageResult


@runtime_checkable
class ImageProvider(Protocol):
    """Provider-agnostic image generation interface."""

    @property
    def name(self) -> str:
        """Stable provider identifier (e.g. ``runpod``)."""

    def generate(self, prompt: str, params: GenerationParams) -> ImageResult:
        """Render ``prompt`` using ``params`` and return an :class:`ImageResult`."""
