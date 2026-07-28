"""Cinematic planning models for Director AI v2."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, field_validator, model_validator

from src.models.base import StrictModel
from src.models.memory import SceneContinuityMeta

if TYPE_CHECKING:
    from src.models.storyboard import DirectorPlan, Scene

_DEFAULT_KEEP = ("character", "costume", "lighting", "location")
_DEFAULT_CHANGE = ("emotion", "camera")


def _normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


class ScenePlan(StrictModel):
    """Structured cinematic plan for one scene (not a raw image prompt).

    The director / :class:`~src.director.planner.StoryPlanner` produce these.
    :class:`~src.prompt.composer.PromptComposer` converts them into
    model-specific positive/negative prompts.
    """

    id: int = Field(ge=1)
    title: str
    description: str
    # Content beats (optional — filled by planner when available).
    subject: str = ""
    environment: str = ""
    action: str = ""
    # Cinematic language.
    camera_shot: str = ""
    camera_movement: str = ""
    camera_angle: str = ""
    lens: str = ""
    lighting: str = ""
    composition: str = ""
    emotion: str = ""
    continuity: str = ""
    # Sprint 5.2 structured continuity (optional for LLM BC).
    continuity_meta: SceneContinuityMeta | None = None
    negative_prompt: str = ""

    @field_validator(
        "title",
        "description",
        "subject",
        "environment",
        "action",
        "camera_shot",
        "camera_movement",
        "camera_angle",
        "lens",
        "lighting",
        "composition",
        "emotion",
        "continuity",
        "negative_prompt",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    def camera_directive(self) -> str:
        """Join camera-related fields into one composer-ready fragment."""
        parts = [
            self.camera_shot,
            self.camera_angle,
            self.lens,
            self.camera_movement,
        ]
        return ", ".join(part for part in parts if part.strip())

    def ensure_continuity_meta(self) -> ScenePlan:
        """Fill default previous_scene / keep / change when missing."""
        if self.continuity_meta is not None:
            meta = self.continuity_meta
            previous = meta.previous_scene
            if not previous and self.id > 1:
                previous = f"scene_{self.id - 1}"
            keep = list(meta.keep) or list(_DEFAULT_KEEP)
            change = list(meta.change) or list(_DEFAULT_CHANGE)
            if self.id == 1:
                previous = previous or ""
                keep = list(meta.keep) if meta.keep else list(_DEFAULT_KEEP)
                change = list(meta.change) if meta.change else list(_DEFAULT_CHANGE)
            updated = SceneContinuityMeta(
                previous_scene=previous,
                keep=keep,
                change=change,
            )
            return self.model_copy(update={"continuity_meta": updated})

        previous = f"scene_{self.id - 1}" if self.id > 1 else ""
        return self.model_copy(
            update={
                "continuity_meta": SceneContinuityMeta(
                    previous_scene=previous,
                    keep=list(_DEFAULT_KEEP),
                    change=list(_DEFAULT_CHANGE),
                )
            }
        )

    def to_scene(self) -> Scene:
        """Project to the pipeline :class:`~src.models.storyboard.Scene` shape."""
        from src.models.storyboard import Scene

        return Scene(
            id=self.id,
            title=self.title,
            description=self.description,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class StoryPlan(StrictModel):
    """Full cinematic story plan produced by :class:`StoryPlanner`."""

    topic: str
    scenes: list[ScenePlan] = Field(min_length=4, max_length=4)

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, value: object) -> object:
        return _normalize_text(value)

    @model_validator(mode="after")
    def _require_contiguous_ids(self) -> StoryPlan:
        for index, scene in enumerate(self.scenes, start=1):
            if scene.id != index:
                raise ValueError(
                    f"ScenePlan ids must be contiguous 1..4; "
                    f"expected id={index}, got id={scene.id}"
                )
        return self

    def with_continuity_links(self) -> StoryPlan:
        """Ensure every scene has structured continuity metadata."""
        return self.model_copy(
            update={"scenes": [scene.ensure_continuity_meta() for scene in self.scenes]}
        )

    def to_director_plan(self) -> DirectorPlan:
        """Convert to a backward-compatible :class:`DirectorPlan`.

        Rich :class:`ScenePlan` values are retained on
        ``DirectorPlan.scene_plans`` for PromptComposer.
        """
        from src.models.storyboard import DirectorPlan

        linked = self.with_continuity_links()
        return DirectorPlan(
            topic=linked.topic,
            scenes=[scene.to_scene() for scene in linked.scenes],
            scene_plans=list(linked.scenes),
        )

    @classmethod
    def from_director_plan(cls, plan: DirectorPlan) -> StoryPlan:
        """Rebuild a :class:`StoryPlan` from a :class:`DirectorPlan`.

        Prefers ``scene_plans`` when present; otherwise lifts title/description
        from legacy :class:`Scene` rows.
        """
        if plan.scene_plans:
            return cls(topic=plan.topic, scenes=list(plan.scene_plans))
        return cls(
            topic=plan.topic,
            scenes=[
                ScenePlan(
                    id=scene.id,
                    title=scene.title,
                    description=scene.description,
                )
                for scene in plan.scenes
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
