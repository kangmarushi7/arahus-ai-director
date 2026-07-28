"""Structured copilot commands (intent → executable ops)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from src.models.base import StrictModel


class CommandType(str, Enum):
    EDIT_SCENE = "edit_scene"
    REGENERATE_IMAGE = "regenerate_image"
    REGENERATE_VIDEO = "regenerate_video"
    MODIFY_CHARACTER = "modify_character"
    MODIFY_WORLD = "modify_world"
    MODIFY_STYLE = "modify_style"
    REORDER_SCENES = "reorder_scenes"
    CHANGE_DURATION = "change_duration"
    CHANGE_CAMERA = "change_camera"
    CHANGE_LIGHTING = "change_lighting"
    CHANGE_EMOTION = "change_emotion"


class CopilotCommand(StrictModel):
    """One validated studio mutation proposed by the copilot."""

    type: CommandType
    scene_id: int | None = Field(default=None, ge=1)
    scene_ids: list[int] | None = None
    field: str | None = None
    value: Any = None
    updates: dict[str, Any] = Field(default_factory=dict)
    target_name: str | None = None
    summary: str = ""

    @field_validator("summary", "field", "target_name", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    def label(self) -> str:
        if self.summary:
            return self.summary
        if self.type == CommandType.REORDER_SCENES:
            return f"Reorder scenes → {self.scene_ids}"
        if self.scene_id is not None:
            return f"{self.type.value} on scene {self.scene_id}"
        if self.target_name:
            return f"{self.type.value}: {self.target_name}"
        return self.type.value


class CommandProposal(StrictModel):
    """Parsed intent ready for preview / confirm."""

    proposal_id: str
    project_id: str
    message: str
    reply: str
    commands: list[CopilotCommand] = Field(default_factory=list)
    status: Literal["pending", "executed", "cancelled"] = "pending"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
