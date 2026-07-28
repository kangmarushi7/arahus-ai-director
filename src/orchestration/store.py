"""Persist execution graphs for replay / debugging / checkpoint recovery."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from src.orchestration.models import ExecutionGraph

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_DEFAULT_ROOT = Path("artifacts") / "orchestration"


class OrchestrationStore:
    """JSON persistence for :class:`ExecutionGraph` documents."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, run_id: str) -> Path:
        safe = (
            " ".join(run_id.split())
            .replace("..", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
        return self._root / f"{safe}.json"

    def save(self, graph: ExecutionGraph) -> Path:
        path = self.path_for(graph.id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(graph.to_dict(), indent=2, sort_keys=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            last_error: Exception | None = None
            for delay in (0.0, 0.02, 0.05, 0.1, 0.2):
                if delay:
                    time.sleep(delay)
                try:
                    tmp.replace(path)
                    last_error = None
                    break
                except PermissionError as exc:  # Windows file lock
                    last_error = exc
            if last_error is not None:
                # Fallback: in-place write when replace is locked
                path.write_text(payload, encoding="utf-8")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            index = self._root / "index.jsonl"
            with index.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": graph.id,
                            "name": graph.name,
                            "topic": graph.topic,
                            "status": graph.status.value,
                            "updated_at": graph.updated_at,
                        }
                    )
                    + "\n"
                )
        logger.debug("event=orch_graph_saved run_id=%s path=%s", graph.id, path)
        return path

    def load(self, run_id: str) -> ExecutionGraph | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        try:
            return ExecutionGraph.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event=orch_graph_load_failed run_id=%r error=%s", run_id, exc
            )
            return None

    def list_ids(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json") if p.stem != "index")
