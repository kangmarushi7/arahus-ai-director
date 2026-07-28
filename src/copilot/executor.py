"""Execute copilot commands through StoryboardStudio + memory store only."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from src.copilot.commands import CommandType, CopilotCommand
from src.models.memory import (
    CharacterBible,
    LocationBible,
    ProjectMemory,
    StyleBible,
)
from src.studio.models import Storyboard
from src.studio.service import StoryboardStudio

ImageGen = Callable[..., Any]
VideoGen = Callable[..., Any]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _default_image_generator() -> ImageGen | None:
    try:
        from src.api.services.projects import image_generator_fn

        return image_generator_fn
    except Exception:  # noqa: BLE001
        return None


def _default_video_generator() -> VideoGen | None:
    try:
        from src.api.services.projects import video_generator_fn

        return video_generator_fn
    except Exception:  # noqa: BLE001
        return None


class CopilotExecutor:
    """Applies structured commands via existing studio / memory APIs."""

    def __init__(
        self,
        studio: StoryboardStudio,
        *,
        image_generator: ImageGen | None = None,
        video_generator: VideoGen | None = None,
    ) -> None:
        self._studio = studio
        self._image_generator = image_generator
        self._video_generator = video_generator

    def apply(
        self,
        commands: list[CopilotCommand],
        *,
        storyboard: Storyboard | None,
        memory: ProjectMemory | None,
        persist: bool,
        run_media: bool = False,
    ) -> tuple[Storyboard | None, ProjectMemory | None, list[str]]:
        board = storyboard
        mem = memory
        notes: list[str] = []
        for command in commands:
            board, mem, note = self._apply_one(
                command,
                storyboard=board,
                memory=mem,
                persist=persist,
                run_media=run_media,
            )
            notes.append(note)
        return board, mem, notes

    def _apply_one(
        self,
        command: CopilotCommand,
        *,
        storyboard: Storyboard | None,
        memory: ProjectMemory | None,
        persist: bool,
        run_media: bool,
    ) -> tuple[Storyboard | None, ProjectMemory | None, str]:
        if command.type == CommandType.REORDER_SCENES:
            if storyboard is None:
                raise ValueError("Storyboard required for reorder")
            if not command.scene_ids:
                raise ValueError("scene_ids required")
            board = self._studio.reorder_scenes(
                storyboard, command.scene_ids, persist=persist
            )
            return board, memory, command.label()

        if command.type in {
            CommandType.EDIT_SCENE,
            CommandType.CHANGE_DURATION,
            CommandType.CHANGE_CAMERA,
            CommandType.CHANGE_LIGHTING,
            CommandType.CHANGE_EMOTION,
        }:
            if storyboard is None or command.scene_id is None:
                raise ValueError("Storyboard + scene_id required")
            updates = dict(command.updates)
            if command.value is not None and command.type == CommandType.CHANGE_DURATION:
                updates["duration_seconds"] = float(command.value)
            if command.value is not None and command.type == CommandType.CHANGE_CAMERA:
                updates.setdefault("camera", str(command.value))
            if command.value is not None and command.type == CommandType.CHANGE_LIGHTING:
                updates.setdefault("lighting", str(command.value))
            if command.value is not None and command.type == CommandType.CHANGE_EMOTION:
                updates.setdefault("emotion", str(command.value))
            scene = storyboard.scene_by_id(command.scene_id)
            board = self._studio._commit_scene(
                storyboard,
                command.scene_id,
                status=scene.status,
                change_summary=command.label(),
                extra_updates=updates,
                persist=persist,
                force_status=True,
            )
            return board, memory, command.label()

        if command.type == CommandType.REGENERATE_IMAGE:
            if storyboard is None or command.scene_id is None:
                raise ValueError("Storyboard + scene_id required")
            board = self._studio.regenerate(
                storyboard,
                command.scene_id,
                "image",
                persist=False,
            )
            image_gen = self._image_generator or _default_image_generator()
            if run_media and image_gen is not None:
                result = self._studio.execute(
                    board,
                    scene_id=command.scene_id,
                    media="images",
                    image_generator=image_gen,
                    project_memory=memory,
                    dry_run=False,
                    persist=persist,
                )
                board = result.storyboard
            elif persist:
                board = self._studio.save(board)
            return board, memory, command.label()

        if command.type == CommandType.REGENERATE_VIDEO:
            if storyboard is None or command.scene_id is None:
                raise ValueError("Storyboard + scene_id required")
            board = self._studio.regenerate(
                storyboard,
                command.scene_id,
                "video",
                persist=False,
            )
            video_gen = self._video_generator or _default_video_generator()
            if run_media and video_gen is not None:
                result = self._studio.execute(
                    board,
                    scene_id=command.scene_id,
                    media="videos",
                    video_generator=video_gen,
                    project_memory=memory,
                    dry_run=False,
                    persist=persist,
                )
                board = result.storyboard
            elif persist:
                board = self._studio.save(board)
            return board, memory, command.label()

        if command.type == CommandType.MODIFY_CHARACTER:
            return storyboard, self._patch_character(memory, command), command.label()

        if command.type == CommandType.MODIFY_WORLD:
            return storyboard, self._patch_world(memory, command), command.label()

        if command.type == CommandType.MODIFY_STYLE:
            return storyboard, self._patch_style(memory, command), command.label()

        raise ValueError(f"Unsupported command type: {command.type}")

    def _ensure_memory(self, memory: ProjectMemory | None) -> ProjectMemory:
        if memory is not None:
            return memory
        raise ValueError("Project memory is required for this command")

    def _patch_character(
        self, memory: ProjectMemory | None, command: CopilotCommand
    ) -> ProjectMemory:
        mem = self._ensure_memory(memory)
        target = (command.target_name or "").casefold()
        characters = list(mem.characters)
        idx = 0
        for i, char in enumerate(characters):
            if target and (
                target in char.name.casefold() or target == char.id.casefold()
            ):
                idx = i
                break
        if not characters:
            raise ValueError("No characters in project memory")
        current = characters[idx]
        data = current.model_dump(mode="python")
        merged = _deep_merge(data, command.updates)
        if "age" in command.updates and "appearance" not in command.updates:
            merged.setdefault("appearance", {})
            if isinstance(merged["appearance"], dict):
                merged["appearance"]["age"] = command.updates["age"]
        characters[idx] = CharacterBible.model_validate(merged)
        return mem.model_copy(update={"characters": characters})

    def _patch_world(
        self, memory: ProjectMemory | None, command: CopilotCommand
    ) -> ProjectMemory:
        mem = self._ensure_memory(memory)
        world = mem.world.model_copy(deep=True)
        updates = dict(command.updates)
        if "era" in updates:
            world = world.model_copy(update={"era": str(updates.pop("era"))})
        if "season" in updates:
            world = world.model_copy(update={"season": str(updates.pop("season"))})
        if "notes" in updates:
            world = world.model_copy(update={"notes": str(updates.pop("notes"))})
        loc_notes = updates.pop("location_notes", None)
        loc_name = updates.pop("location_name", None)
        locations = list(world.locations)
        if locations:
            loc = locations[0]
            patch: dict[str, Any] = {}
            if loc_notes:
                patch["notes"] = str(loc_notes)
            if loc_name:
                patch["name"] = str(loc_name)
            patch.update(updates)
            locations[0] = loc.model_copy(update=patch)
            world = world.model_copy(update={"locations": locations})
        elif loc_name or loc_notes:
            locations = [
                LocationBible(
                    id="loc_1",
                    asset_id=1,
                    name=str(loc_name or "Primary"),
                    notes=str(loc_notes or ""),
                )
            ]
            world = world.model_copy(update={"locations": locations})
        return mem.model_copy(update={"world": world})

    def _patch_style(
        self, memory: ProjectMemory | None, command: CopilotCommand
    ) -> ProjectMemory:
        mem = self._ensure_memory(memory)
        style = mem.style or StyleBible()
        style = style.model_copy(update=command.updates)
        return mem.model_copy(update={"style": style})


def clone_board(board: Storyboard | None) -> Storyboard | None:
    if board is None:
        return None
    return Storyboard.from_dict(deepcopy(board.to_dict()))


def clone_memory(memory: ProjectMemory | None) -> ProjectMemory | None:
    if memory is None:
        return None
    return ProjectMemory.from_dict(deepcopy(memory.to_dict()))
