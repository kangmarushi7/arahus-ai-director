"""File-backed persistence for per-project Character & World Memory."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.models.memory import ProjectMemory

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("artifacts") / "projects"
_lock = threading.RLock()


class ProjectMemoryStore:
    """Load / save :class:`ProjectMemory` as JSON under ``artifacts/projects``."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, project_id: str) -> Path:
        cleaned = " ".join(project_id.split())
        if not cleaned:
            raise ValueError("project_id must be a non-empty string")
        # Prevent path traversal while keeping readable folder names.
        safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "memory.json"

    def load(self, project_id: str) -> ProjectMemory | None:
        path = self.path_for(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            memory = ProjectMemory.from_dict(payload)
            logger.info(
                "event=project_memory_loaded project_id=%r path=%s characters=%s "
                "locations=%s",
                project_id,
                path,
                len(memory.characters),
                len(memory.world.locations),
            )
            return memory
        except Exception as exc:  # noqa: BLE001 - best-effort load
            logger.warning(
                "event=project_memory_load_failed project_id=%r error=%s",
                project_id,
                exc,
            )
            return None

    def save(self, memory: ProjectMemory) -> Path:
        path = self.path_for(memory.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(memory.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        logger.info(
            "event=project_memory_saved project_id=%r path=%s characters=%s "
            "locations=%s assets=%s",
            memory.project_id,
            path,
            len(memory.characters),
            len(memory.world.locations),
            len(memory.registry.assets) if memory.registry else 0,
        )
        return path

    def load_or_create(self, project_id: str, *, topic: str = "") -> ProjectMemory:
        existing = self.load(project_id)
        if existing is not None:
            if topic and not existing.topic:
                return existing.model_copy(update={"topic": topic})
            return existing
        return ProjectMemory(project_id=project_id, topic=topic)
