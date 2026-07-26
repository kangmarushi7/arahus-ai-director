"""Aggregate output of a full DirectorPipeline run."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.models.base import StrictModel
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Storyboard


class GeneratedImageInfo(StrictModel):
    """One scene image (or a failure status) for the studio UI."""

    scene_id: int = Field(ge=1)
    title: str
    prompt: str = ""
    url: str | None = None
    status: str = "ok"


class PipelineResult(StrictModel):
    """Every intermediate artifact produced by :meth:`DirectorPipeline.generate`."""

    topic: str
    research: ResearchResult
    plan: DirectorPlan
    storyboard: Storyboard
    review: ReviewResult
    images: list[GeneratedImageInfo] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
