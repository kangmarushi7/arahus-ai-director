"""Models for the director and prompt stages."""

from __future__ import annotations

from pydantic import Field

from src.models.base import StrictModel
from src.models.image import ImageResult
from src.models.scene_plan import ScenePlan


class Scene(StrictModel):
    """A single chronological scene.

    ``image_prompt`` is filled in by the prompt agent and ``image`` by the
    image stage, so both are optional while the scene is still a plain
    narrative beat from the director. ``error`` captures a per-scene image
    failure without aborting the rest of the storyboard.
    """

    id: int = Field(ge=1)
    title: str
    description: str
    image_prompt: str | None = None
    image: ImageResult | None = None
    error: str | None = None


class DirectorPlan(StrictModel):
    """The director's chronological breakdown of a topic into scenes.

    Sprint 5.1: optional ``scene_plans`` carries rich cinematic
    :class:`~src.models.scene_plan.ScenePlan` rows. Legacy callers that only
    read ``scenes`` remain compatible.
    """

    topic: str
    scenes: list[Scene] = Field(min_length=4, max_length=4)
    scene_plans: list[ScenePlan] | None = None


class Storyboard(StrictModel):
    """A director plan enriched with image prompts and rendered images."""

    topic: str
    scenes: list[Scene] = Field(min_length=4, max_length=4)
