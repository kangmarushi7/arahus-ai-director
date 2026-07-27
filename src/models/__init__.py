"""Validated models exchanged between pipeline stages."""

from __future__ import annotations

from typing import Any

from src.models.base import StrictModel
from src.models.image import ImageResult, VideoResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard

__all__ = [
    "DirectorPlan",
    "GeneratedImageInfo",
    "ImageResult",
    "PipelineContext",
    "PipelineResult",
    "ResearchResult",
    "ReviewResult",
    "Scene",
    "Storyboard",
    "StrictModel",
    "VideoResult",
]


def __getattr__(name: str) -> Any:
    """Lazy-load domain-aware models to avoid import cycles with ``src.domain``."""
    if name == "PipelineContext":
        from src.models.context import PipelineContext

        return PipelineContext
    if name == "PipelineResult":
        from src.models.pipeline import PipelineResult

        return PipelineResult
    if name == "GeneratedImageInfo":
        from src.models.pipeline import GeneratedImageInfo

        return GeneratedImageInfo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
