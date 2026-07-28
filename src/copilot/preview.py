"""Build human-readable previews of proposed copilot changes (no persist)."""

from __future__ import annotations

from typing import Any

from src.copilot.commands import CommandType, CopilotCommand
from src.models.memory import ProjectMemory
from src.studio.models import Storyboard


def _scene_snapshot(board: Storyboard, scene_id: int) -> dict[str, Any] | None:
    try:
        scene = board.scene_by_id(scene_id)
    except KeyError:
        return None
    return {
        "id": scene.id,
        "title": scene.title,
        "camera": scene.camera,
        "lighting": scene.lighting,
        "emotion": scene.emotion,
        "duration_seconds": scene.duration_seconds,
        "image_prompt": scene.image_prompt,
        "status": scene.status.value,
        "location": scene.location,
        "characters": list(scene.characters),
    }


def build_preview(
    commands: list[CopilotCommand],
    *,
    storyboard: Storyboard | None,
    memory: ProjectMemory | None,
    simulated_board: Storyboard | None = None,
    simulated_memory: ProjectMemory | None = None,
) -> dict[str, Any]:
    """Diff-oriented preview payload for the Studio chat panel."""
    changes: list[dict[str, Any]] = []
    for command in commands:
        item: dict[str, Any] = {
            "type": command.type.value,
            "summary": command.label(),
            "scene_id": command.scene_id,
            "updates": command.updates or ({"value": command.value} if command.value is not None else {}),
        }
        if storyboard is not None and command.scene_id is not None:
            item["before"] = _scene_snapshot(storyboard, command.scene_id)
            if simulated_board is not None:
                item["after"] = _scene_snapshot(simulated_board, command.scene_id)
        if command.type == CommandType.REORDER_SCENES and storyboard is not None:
            item["before_order"] = [s.id for s in storyboard.scenes]
            item["after_order"] = command.scene_ids
        if command.type in {
            CommandType.MODIFY_CHARACTER,
            CommandType.MODIFY_WORLD,
            CommandType.MODIFY_STYLE,
        }:
            item["target_name"] = command.target_name
            if memory is not None:
                item["memory_before"] = {
                    "characters": [c.name for c in memory.characters],
                    "era": memory.world.era,
                    "style": memory.style.visual_style if memory.style else "",
                }
            if simulated_memory is not None:
                item["memory_after"] = {
                    "characters": [c.name for c in simulated_memory.characters],
                    "era": simulated_memory.world.era,
                    "style": (
                        simulated_memory.style.visual_style
                        if simulated_memory.style
                        else ""
                    ),
                }
        changes.append(item)

    return {
        "summary": "; ".join(c.label() for c in commands) or "No changes",
        "command_count": len(commands),
        "changes": changes,
        "requires_confirmation": True,
    }
