"""Validated models exchanged between pipeline stages."""

from __future__ import annotations

from typing import Any

from src.models.base import StrictModel
from src.models.image import ImageResult, VideoResult
from src.models.memory import (
    AppearanceBible,
    AssetKind,
    AssetRecord,
    AssetRegistry,
    CharacterBible,
    FaceBible,
    HairBible,
    LocationBible,
    ProjectMemory,
    SceneContinuityMeta,
    StyleBible,
    UniformBible,
    WorldBible,
)
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.models.storyboard import DirectorPlan, Scene, Storyboard

__all__ = [
    "AppearanceBible",
    "AssetKind",
    "AssetRecord",
    "AssetRegistry",
    "CharacterBible",
    "DirectorPlan",
    "FaceBible",
    "GeneratedImageInfo",
    "HairBible",
    "ImageResult",
    "LocationBible",
    "PipelineContext",
    "PipelineResult",
    "ProjectMemory",
    "ResearchResult",
    "ReviewResult",
    "Scene",
    "SceneContinuityMeta",
    "ScenePlan",
    "StoryPlan",
    "Storyboard",
    "StrictModel",
    "StyleBible",
    "UniformBible",
    "VideoResult",
    "WorldBible",
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
