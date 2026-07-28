"""File-backed Audio Studio documents."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.audio.models import AudioProject

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_DEFAULT_ROOT = Path("artifacts") / "projects"


class AudioProjectStore:
    """Persist ``audio.json`` beside storyboard / timeline / memory."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, project_id: str) -> Path:
        cleaned = " ".join(project_id.split())
        safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "audio.json"

    def load(self, project_id: str) -> AudioProject | None:
        path = self.path_for(project_id)
        if not path.is_file():
            return None
        try:
            return AudioProject.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event=audio_load_failed project_id=%r error=%s", project_id, exc
            )
            return None

    def save(self, project: AudioProject) -> Path:
        path = self.path_for(project.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(project.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        return path
