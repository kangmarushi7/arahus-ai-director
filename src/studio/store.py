"""File-backed persistence for Storyboard Studio documents."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.studio.models import Storyboard

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("artifacts") / "projects"
_lock = threading.RLock()


class StoryboardStore:
    """Load / save studio :class:`Storyboard` JSON under ``artifacts/projects``."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, project_id: str) -> Path:
        cleaned = " ".join(project_id.split())
        if not cleaned:
            raise ValueError("project_id must be a non-empty string")
        safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "storyboard.json"

    def load(self, project_id: str) -> Storyboard | None:
        path = self.path_for(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            board = Storyboard.from_dict(payload)
            logger.info(
                "event=storyboard_loaded project_id=%r path=%s scenes=%s version=%s",
                project_id,
                path,
                len(board.scenes),
                board.version,
            )
            return board
        except Exception as exc:  # noqa: BLE001 - best-effort load
            logger.warning(
                "event=storyboard_load_failed project_id=%r error=%s",
                project_id,
                exc,
            )
            return None

    def save(self, storyboard: Storyboard) -> Path:
        path = self.path_for(storyboard.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(storyboard.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        logger.info(
            "event=storyboard_saved project_id=%r path=%s scenes=%s version=%s",
            storyboard.project_id,
            path,
            len(storyboard.scenes),
            storyboard.version,
        )
        return path
