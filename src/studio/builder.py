"""Build studio storyboards from director / pipeline artifacts."""

from __future__ import annotations

from src.memory.ids import project_id_for_topic
from src.models.scene_plan import ScenePlan, StoryPlan
from src.models.storyboard import DirectorPlan
from src.models.storyboard import Storyboard as PipelineStoryboard
from src.studio.models import SceneLifecycle, Storyboard, StoryboardScene


def _camera_from_plan(plan: ScenePlan | None) -> str:
    if plan is None:
        return ""
    return plan.camera_directive()


def scene_from_scene_plan(
    plan: ScenePlan,
    *,
    characters: list[str] | None = None,
    duration_seconds: float = 5.0,
) -> StoryboardScene:
    """Create a draft studio scene card from a cinematic :class:`ScenePlan`."""
    return StoryboardScene(
        id=plan.id,
        title=plan.title,
        description=plan.description,
        goal=plan.action or plan.title,
        duration_seconds=duration_seconds,
        characters=list(characters or []),
        location=plan.environment,
        camera=_camera_from_plan(plan),
        emotion=plan.emotion,
        lighting=plan.lighting,
        image_prompt="",
        negative_prompt=plan.negative_prompt,
        status=SceneLifecycle.DRAFT,
        version=1,
        versions=[],
        scene_plan=plan,
    )


def build_from_story_plan(
    plan: StoryPlan,
    *,
    project_id: str | None = None,
    characters: list[str] | None = None,
    duration_seconds: float = 5.0,
) -> Storyboard:
    """Build a studio :class:`Storyboard` from a :class:`StoryPlan`."""
    pid = project_id or project_id_for_topic(plan.topic)
    scenes = [
        scene_from_scene_plan(
            scene_plan,
            characters=characters,
            duration_seconds=duration_seconds,
        )
        for scene_plan in plan.scenes
    ]
    return Storyboard(
        project_id=pid,
        topic=plan.topic,
        scenes=scenes,
        status=SceneLifecycle.DRAFT,
        version=1,
    )


def build_from_director_plan(
    plan: DirectorPlan,
    *,
    project_id: str | None = None,
    characters: list[str] | None = None,
    duration_seconds: float = 5.0,
) -> Storyboard:
    """Build a studio storyboard from a :class:`DirectorPlan`."""
    if plan.scene_plans:
        story = StoryPlan(topic=plan.topic, scenes=list(plan.scene_plans))
        return build_from_story_plan(
            story,
            project_id=project_id,
            characters=characters,
            duration_seconds=duration_seconds,
        )

    pid = project_id or project_id_for_topic(plan.topic)
    scenes = [
        StoryboardScene(
            id=scene.id,
            title=scene.title,
            description=scene.description,
            goal=scene.title,
            duration_seconds=duration_seconds,
            characters=list(characters or []),
            image_prompt=scene.image_prompt or "",
            status=SceneLifecycle.DRAFT,
        )
        for scene in plan.scenes
    ]
    return Storyboard(
        project_id=pid,
        topic=plan.topic,
        scenes=scenes,
        status=SceneLifecycle.DRAFT,
        version=1,
    )


def to_pipeline_storyboard(storyboard: Storyboard) -> PipelineStoryboard:
    """Project studio scenes into the pipeline ReviewAgent storyboard shape.

    The pipeline model requires exactly four scenes. When the studio board has
    a different count, only the first four are projected (padded if fewer).
    """
    from src.models.storyboard import Scene

    raw = list(storyboard.scenes)
    while len(raw) < 4:
        index = len(raw) + 1
        raw.append(
            StoryboardScene(
                id=index,
                title=f"Placeholder {index}",
                description="Placeholder scene for review projection.",
            )
        )
    scenes = [
        Scene(
            id=scene.id,
            title=scene.title,
            description=scene.description,
            image_prompt=scene.image_prompt or None,
            image=scene.image,
            error=scene.error,
        )
        for scene in raw[:4]
    ]
    # Ensure contiguous ids 1..4 for pipeline validators.
    fixed = [
        scene.model_copy(update={"id": index})
        for index, scene in enumerate(scenes, start=1)
    ]
    return PipelineStoryboard(topic=storyboard.topic, scenes=fixed)
