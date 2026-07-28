"""File-backed persistence for project timelines."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.timeline.models import Timeline

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("artifacts") / "projects"
_lock = threading.RLock()


class TimelineStore:
    """Load / save timeline JSON under ``artifacts/projects/{id}/timeline.json``."""

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
        return self._root / safe / "timeline.json"

    def load(self, project_id: str) -> Timeline | None:
        path = self.path_for(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            timeline = Timeline.from_dict(payload)
            logger.info(
                "event=timeline_loaded project_id=%r tracks=%s version=%s",
                project_id,
                len(timeline.tracks),
                timeline.version,
            )
            return timeline
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event=timeline_load_failed project_id=%r error=%s",
                project_id,
                exc,
            )
            return None

    def save(self, timeline: Timeline) -> Path:
        path = self.path_for(timeline.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(timeline.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        logger.info(
            "event=timeline_saved project_id=%r path=%s version=%s",
            timeline.project_id,
            path,
            timeline.version,
        )
        return path
