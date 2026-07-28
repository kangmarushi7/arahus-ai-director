"""Storyboard Studio domain models — persistent collaborative storyboards.

Distinct from :class:`src.models.storyboard.Storyboard` (pipeline 4-scene
render artifact). Studio storyboards are versioned, multi-status project
documents that survive across generate / approve / regenerate cycles.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from src.models.base import StrictModel
from src.models.image import ImageResult, VideoResult
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _strip_computed_review_fields(payload: Any) -> Any:
    """Remove ReviewResult computed aliases that cannot round-trip StrictModel."""
    if isinstance(payload, dict):
        cleaned = {
            key: _strip_computed_review_fields(value)
            for key, value in payload.items()
            if not (key == "historical_accuracy")
        }
        return cleaned
    if isinstance(payload, list):
        return [_strip_computed_review_fields(item) for item in payload]
    return payload


class SceneLifecycle(str, Enum):
    """Lifecycle status for one storyboard scene card."""

    DRAFT = "draft"
    APPROVED = "approved"
    IMAGE_GENERATED = "image_generated"
    IMAGE_APPROVED = "image_approved"
    VIDEO_GENERATED = "video_generated"
    VIDEO_APPROVED = "video_approved"
    LOCKED = "locked"


RegenerateTarget = Literal["camera", "prompt", "image", "video", "scene"]


class SceneVersion(StrictModel):
    """Immutable snapshot of a scene at one point in its history."""

    version: int = Field(ge=1)
    created_at: str = Field(default_factory=_utc_iso)
    status: SceneLifecycle
    title: str = ""
    description: str = ""
    goal: str = ""
    image_prompt: str = ""
    camera: str = ""
    emotion: str = ""
    lighting: str = ""
    change_summary: str = ""
    review_score: float | None = Field(default=None, ge=0, le=100)

    @field_validator(
        "title",
        "description",
        "goal",
        "image_prompt",
        "camera",
        "emotion",
        "lighting",
        "change_summary",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


class StoryboardScene(StrictModel):
    """One scene card in the Storyboard Studio."""

    id: int = Field(ge=1)
    title: str
    description: str = ""
    goal: str = ""
    duration_seconds: float = Field(default=5.0, ge=0.1)
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    camera: str = ""
    emotion: str = ""
    lighting: str = ""
    image_prompt: str = ""
    negative_prompt: str = ""
    status: SceneLifecycle = SceneLifecycle.DRAFT
    version: int = Field(default=1, ge=1)
    versions: list[SceneVersion] = Field(default_factory=list)
    scene_plan: ScenePlan | None = None
    image: ImageResult | None = None
    video: VideoResult | None = None
    image_asset_id: int | None = Field(default=None, ge=1)
    video_asset_id: int | None = Field(default=None, ge=1)
    review: ReviewResult | None = None
    error: str | None = None
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)

    @field_validator(
        "title",
        "description",
        "goal",
        "location",
        "camera",
        "emotion",
        "lighting",
        "image_prompt",
        "negative_prompt",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("characters", mode="before")
    @classmethod
    def _normalize_characters(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [part for part in parts if part]
        if isinstance(value, (list, tuple)):
            return [" ".join(str(item).split()) for item in value if str(item).strip()]
        return value

    @property
    def is_failed(self) -> bool:
        return bool(self.error)

    @property
    def is_locked(self) -> bool:
        return self.status == SceneLifecycle.LOCKED

    def snapshot(self, *, change_summary: str = "") -> SceneVersion:
        """Build an immutable version row from the current scene state."""
        return SceneVersion(
            version=self.version,
            created_at=_utc_iso(),
            status=self.status,
            title=self.title,
            description=self.description,
            goal=self.goal,
            image_prompt=self.image_prompt,
            camera=self.camera,
            emotion=self.emotion,
            lighting=self.lighting,
            change_summary=change_summary,
            review_score=(
                self.review.overall_score if self.review is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _strip_computed_review_fields(self.model_dump(mode="json"))


class Storyboard(StrictModel):
    """Persistent project storyboard (Studio document).

    Not the pipeline :class:`~src.models.storyboard.Storyboard` render DTO.
    """

    project_id: str
    topic: str
    scenes: list[StoryboardScene] = Field(default_factory=list)
    status: SceneLifecycle = SceneLifecycle.DRAFT
    version: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)
    review: ReviewResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id", "topic", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @model_validator(mode="after")
    def _require_unique_scene_ids(self) -> Storyboard:
        seen: set[int] = set()
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"Duplicate storyboard scene id: {scene.id}")
            seen.add(scene.id)
        return self

    def scene_by_id(self, scene_id: int) -> StoryboardScene:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        raise KeyError(f"Scene {scene_id} not found in storyboard")

    def touch(self) -> Storyboard:
        return self.model_copy(update={"updated_at": _utc_iso()})

    def to_dict(self) -> dict[str, Any]:
        return _strip_computed_review_fields(self.model_dump(mode="json"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Storyboard:
        return cls.model_validate(_strip_computed_review_fields(data))


class CostEstimate(StrictModel):
    """Pre-generation cost / GPU time estimate for a pending selection."""

    image_count: int = Field(ge=0, default=0)
    video_count: int = Field(ge=0, default=0)
    scene_ids: list[int] = Field(default_factory=list)
    estimated_gpu_seconds: float = Field(ge=0.0, default=0.0)
    estimated_cost_usd: float = Field(ge=0.0, default=0.0)
    cost_per_image: float = Field(ge=0.0, default=0.0)
    cost_per_video_second: float = Field(ge=0.0, default=0.0)
    video_duration_seconds: float = Field(ge=0.0, default=0.0)
    breakdown: dict[str, Any] = Field(default_factory=dict)

    @property
    def estimated_gpu_minutes(self) -> float:
        return round(self.estimated_gpu_seconds / 60.0, 2)

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["estimated_gpu_minutes"] = self.estimated_gpu_minutes
        return payload


class PartialExecutionPlan(StrictModel):
    """Resolved partial-execution selection before media work."""

    scene_ids: list[int] = Field(default_factory=list)
    media: Literal["images", "videos", "both"] = "both"
    retry_failed: bool = False
    estimate: CostEstimate | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PartialExecutionResult(StrictModel):
    """Outcome of a studio partial execution (may be dry-run)."""

    plan: PartialExecutionPlan
    storyboard: Storyboard
    dry_run: bool = True
    generated_images: list[int] = Field(default_factory=list)
    generated_videos: list[int] = Field(default_factory=list)
    skipped: list[int] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
