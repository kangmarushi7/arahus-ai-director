"""Models for the storyboard review stage."""

from __future__ import annotations

from pydantic import AliasChoices, ConfigDict, Field, computed_field

from src.models.base import StrictModel


class ReviewResult(StrictModel):
    """Quality assessment of a storyboard before image generation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    overall_score: float = Field(ge=0, le=100)
    domain_accuracy: float = Field(
        ge=0,
        le=100,
        validation_alias=AliasChoices("domain_accuracy", "historical_accuracy"),
    )
    visual_quality: float = Field(ge=0, le=100)
    scene_continuity: float = Field(ge=0, le=100)
    prompt_quality: float = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    approved: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def historical_accuracy(self) -> float:
        """Deprecated alias of :attr:`domain_accuracy` for Studio compatibility."""
        return self.domain_accuracy
