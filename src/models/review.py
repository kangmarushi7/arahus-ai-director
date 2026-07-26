"""Models for the storyboard review stage."""

from __future__ import annotations

from pydantic import Field

from src.models.base import StrictModel


class ReviewResult(StrictModel):
    """Quality assessment of a storyboard before image generation."""

    overall_score: float = Field(ge=0, le=100)
    historical_accuracy: float = Field(ge=0, le=100)
    visual_quality: float = Field(ge=0, le=100)
    scene_continuity: float = Field(ge=0, le=100)
    prompt_quality: float = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    approved: bool
