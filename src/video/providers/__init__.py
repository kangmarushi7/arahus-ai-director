"""Video providers package."""

from __future__ import annotations

from src.video.providers.base import VideoProvider
from src.video.providers.runpod import RunPodVideoProvider

__all__ = ["RunPodVideoProvider", "VideoProvider"]
