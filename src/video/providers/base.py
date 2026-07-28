"""Video provider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.media.base import MediaKind, MediaProvider
from src.models.image import VideoResult
from src.video.models import VideoGenerationParams, VideoRequest


@runtime_checkable
class VideoProvider(MediaProvider, Protocol):
    """Provider-agnostic video generation interface."""

    @property
    def name(self) -> str:
        """Stable provider identifier (e.g. ``runpod``)."""

    @property
    def kind(self) -> MediaKind:
        """Always :attr:`MediaKind.VIDEO`."""

    def generate(
        self,
        request: VideoRequest,
        params: VideoGenerationParams,
    ) -> VideoResult:
        """Render ``request`` using ``params`` and return a :class:`VideoResult`.

        Implementations must support both text-to-video and image-to-video based
        on whether ``request.source_image`` / ``source_image_urls`` are set.
        """
