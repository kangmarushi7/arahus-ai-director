"""Undo / redo stacks backed by storyboard + memory snapshots."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from src.models.base import StrictModel

_lock = threading.RLock()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UndoEntry(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str
    proposal_id: str | None = None
    label: str = ""
    created_at: str = Field(default_factory=_utc_iso)
    before_storyboard: dict[str, Any] | None = None
    after_storyboard: dict[str, Any] | None = None
    before_memory: dict[str, Any] | None = None
    after_memory: dict[str, Any] | None = None


class UndoState(StrictModel):
    project_id: str
    undo_stack: list[UndoEntry] = Field(default_factory=list)
    redo_stack: list[UndoEntry] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UndoStore:
    """Persist undo/redo stacks per project."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else Path("artifacts") / "projects"

    def path_for(self, project_id: str) -> Path:
        cleaned = " ".join(project_id.split())
        safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "copilot_undo.json"

    def load(self, project_id: str) -> UndoState:
        path = self.path_for(project_id)
        if not path.is_file():
            return UndoState(project_id=project_id)
        try:
            return UndoState.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception:  # noqa: BLE001
            return UndoState(project_id=project_id)

    def save(self, state: UndoState) -> Path:
        path = self.path_for(state.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(state.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        return path

    def push(self, entry: UndoEntry) -> UndoState:
        state = self.load(entry.project_id)
        state.undo_stack.append(entry)
        state.redo_stack = []
        # Cap history
        if len(state.undo_stack) > 40:
            state.undo_stack = state.undo_stack[-40:]
        self.save(state)
        return state
