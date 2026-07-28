"""Storyboard Studio — persistent collaborative storyboard workflow.

Additive to :meth:`DirectorPipeline.generate` (public API unchanged).
"""

from __future__ import annotations

from src.studio.builder import (
    build_from_director_plan,
    build_from_story_plan,
    scene_from_scene_plan,
    to_pipeline_storyboard,
)
from src.studio.estimates import estimate_generation_cost
from src.studio.models import (
    CostEstimate,
    PartialExecutionPlan,
    PartialExecutionResult,
    SceneLifecycle,
    SceneVersion,
    Storyboard,
    StoryboardScene,
)
from src.studio.selection import filter_scenes, resolve_scene_ids
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore
from src.studio.transitions import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    assert_transition,
    can_transition,
    next_status,
    rollback_for,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "CostEstimate",
    "PartialExecutionPlan",
    "PartialExecutionResult",
    "SceneLifecycle",
    "SceneVersion",
    "Storyboard",
    "StoryboardScene",
    "StoryboardStore",
    "StoryboardStudio",
    "TransitionError",
    "assert_transition",
    "build_from_director_plan",
    "build_from_story_plan",
    "can_transition",
    "estimate_generation_cost",
    "filter_scenes",
    "next_status",
    "resolve_scene_ids",
    "rollback_for",
    "scene_from_scene_plan",
    "to_pipeline_storyboard",
]
