"""Shared media engine contracts for image, video, and future modalities."""

from __future__ import annotations

from src.media.assets import register_scene_video
from src.media.base import MediaKind, MediaProvider
from src.media.request import MediaRequest, QualityMode, GenerationProfileName
from src.media.result import MediaGenerationMetrics
from src.media.router import MediaRouter

__all__ = [
    "GenerationProfileName",
    "MediaGenerationMetrics",
    "MediaKind",
    "MediaProvider",
    "MediaRequest",
    "MediaRouter",
    "QualityMode",
    "register_scene_video",
]
