"""Build video prompts from cinematic ScenePlans / director language."""

from __future__ import annotations

from typing import Any

from src.models.scene_plan import ScenePlan


def compose_video_prompt_from_scene_plan(
    scene_plan: ScenePlan,
    *,
    base_prompt: str | None = None,
) -> str:
    """Turn ScenePlan camera / motion / emotion / lighting into a video prompt.

    Uses an optional ``base_prompt`` (e.g. from PromptComposer) and appends
    motion-oriented cinematic directives the image prompt may under-emphasize.
    """
    if not isinstance(scene_plan, ScenePlan):
        raise TypeError("scene_plan must be a ScenePlan instance")

    parts: list[str] = []
    if base_prompt and base_prompt.strip():
        parts.append(" ".join(base_prompt.split()))
    else:
        core = [
            scene_plan.subject or scene_plan.title,
            scene_plan.action,
            scene_plan.environment,
        ]
        parts.append(", ".join(part for part in core if part.strip()))

    motion_bits = [
        ("camera shot", scene_plan.camera_shot),
        ("camera movement", scene_plan.camera_movement),
        ("camera angle", scene_plan.camera_angle),
        ("lens", scene_plan.lens),
        ("lighting", scene_plan.lighting),
        ("emotion", scene_plan.emotion),
        ("composition", scene_plan.composition),
    ]
    for label, value in motion_bits:
        if value and value.strip():
            parts.append(f"{label}: {value.strip()}")

    if scene_plan.continuity_meta is not None:
        continuity = scene_plan.continuity_meta.to_prompt_fragment()
        if continuity:
            parts.append(continuity)
    elif scene_plan.continuity.strip():
        parts.append(scene_plan.continuity)

    return ", ".join(part for part in parts if part)


def cinematic_fields_for_video(scene_plan: ScenePlan) -> dict[str, Any]:
    """Export ScenePlan cinematic fields for video request metadata."""
    return {
        "camera_shot": scene_plan.camera_shot,
        "camera_movement": scene_plan.camera_movement,
        "camera_angle": scene_plan.camera_angle,
        "lens": scene_plan.lens,
        "lighting": scene_plan.lighting,
        "emotion": scene_plan.emotion,
        "composition": scene_plan.composition,
        "continuity": scene_plan.continuity,
    }
