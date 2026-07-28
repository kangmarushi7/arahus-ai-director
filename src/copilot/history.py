"""Persist copilot chat history per project."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from src.models.base import StrictModel

_lock = threading.RLock()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatMessage(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: Literal["user", "assistant", "system"] = "user"
    content: str
    created_at: str = Field(default_factory=_utc_iso)
    proposal_id: str | None = None
    commands: list[dict[str, Any]] = Field(default_factory=list)
    preview: dict[str, Any] | None = None
    executed: bool = False


class ChatHistory(StrictModel):
    project_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ChatHistoryStore:
    """File-backed chat transcripts under ``artifacts/projects/{id}/chat.json``."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else Path("artifacts") / "projects"

    def path_for(self, project_id: str) -> Path:
        cleaned = " ".join(project_id.split())
        safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "chat.json"

    def load(self, project_id: str) -> ChatHistory:
        path = self.path_for(project_id)
        if not path.is_file():
            return ChatHistory(project_id=project_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ChatHistory.model_validate(payload)
        except Exception:  # noqa: BLE001
            return ChatHistory(project_id=project_id)

    def save(self, history: ChatHistory) -> Path:
        path = self.path_for(history.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(history.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        return path

    def append(
        self,
        project_id: str,
        message: ChatMessage,
        *,
        pending_proposal_id: str | None = None,
    ) -> ChatHistory:
        history = self.load(project_id)
        history.messages.append(message)
        if pending_proposal_id is not None:
            history.pending_proposal_id = pending_proposal_id
        self.save(history)
        return history
