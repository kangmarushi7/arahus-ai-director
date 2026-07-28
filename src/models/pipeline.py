"""Aggregate output of a full DirectorPipeline run."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.domain.models import DomainInfo
from src.domain.prompt_context import DomainPromptContext
from src.models.base import StrictModel
from src.models.context import PipelineContext
from src.models.memory import ProjectMemory
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
    asset_id: int | None = Field(default=None, ge=1)


class PipelineResult(StrictModel):
    """Every intermediate artifact produced by :meth:`DirectorPipeline.generate`."""

    topic: str
    research: ResearchResult
    plan: DirectorPlan
    storyboard: Storyboard
    review: ReviewResult
    images: list[GeneratedImageInfo] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    domain_info: DomainInfo | None = None
    prompt_context: DomainPromptContext | None = None
    context: PipelineContext | None = None
    using_stub_services: bool = False
    character_bible: str = ""
    project_id: str = ""
    project_memory: ProjectMemory | None = None
    run_id: str | None = None
