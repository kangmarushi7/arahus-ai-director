"""Scene selection helpers for partial studio execution."""

from __future__ import annotations

from collections.abc import Sequence

from src.studio.models import Storyboard, StoryboardScene


def resolve_scene_ids(
    storyboard: Storyboard,
    *,
    scene_id: int | None = None,
    scene_ids: Sequence[int] | None = None,
    scene_range: tuple[int, int] | None = None,
    retry_failed: bool = False,
) -> list[int]:
    """Resolve a partial-execution scene selection.

    Precedence:
    1. Explicit ``scene_id`` / ``scene_ids``
    2. Inclusive ``scene_range`` (start, end)
    3. All scenes

    When ``retry_failed`` is True, the selection is filtered to scenes with
    ``error`` set (intersected with the selection above).
    """
    available = {scene.id: scene for scene in storyboard.scenes}
    if not available:
        return []

    selected: list[int]
    if scene_id is not None:
        selected = [int(scene_id)]
    elif scene_ids is not None:
        selected = [int(item) for item in scene_ids]
    elif scene_range is not None:
        start, end = int(scene_range[0]), int(scene_range[1])
        if start > end:
            start, end = end, start
        selected = [sid for sid in range(start, end + 1) if sid in available]
    else:
        selected = sorted(available)

    # Drop unknown ids.
    selected = [sid for sid in selected if sid in available]

    if retry_failed:
        selected = [
            sid for sid in selected if available[sid].is_failed
        ]

    return selected


def filter_scenes(
    storyboard: Storyboard,
    scene_ids: Sequence[int],
) -> list[StoryboardScene]:
    """Return scenes in storyboard order matching ``scene_ids``."""
    wanted = {int(item) for item in scene_ids}
    return [scene for scene in storyboard.scenes if scene.id in wanted]
