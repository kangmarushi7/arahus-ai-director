"""Persist export studio state + job artifacts."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.export.models import ExportStudioState
from src.security.paths import safe_path_segment

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_DEFAULT_ROOT = Path("artifacts") / "projects"


class ExportStore:
    """``export.json`` + ``exports/`` artifact directory per project."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def project_dir(self, project_id: str) -> Path:
        return self._root / safe_path_segment(project_id)

    def state_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "export.json"

    def exports_dir(self, project_id: str) -> Path:
        path = self.project_dir(project_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def job_dir(self, project_id: str, job_id: str) -> Path:
        path = self.exports_dir(project_id) / safe_path_segment(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load(self, project_id: str) -> ExportStudioState | None:
        path = self.state_path(project_id)
        if not path.is_file():
            return None
        try:
            return ExportStudioState.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event=export_load_failed project_id=%r error=%s", project_id, exc
            )
            return None

    def save(self, state: ExportStudioState) -> Path:
        path = self.state_path(state.project_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(state.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        return path
