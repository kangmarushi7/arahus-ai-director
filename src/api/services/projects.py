"""Thin API services that wrap existing Studio / Memory / Pipeline code."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.memory.ids import project_id_for_topic
from src.memory.store import ProjectMemoryStore
from src.models.image import ImageResult, VideoResult
from src.models.pipeline import PipelineResult
from src.studio.models import SceneLifecycle, Storyboard, StoryboardScene
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path("artifacts") / "projects"
_lock = threading.RLock()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRecord:
    """Lightweight project metadata persisted beside memory/storyboard JSON."""

    def __init__(
        self,
        *,
        id: str,
        topic: str,
        status: str = "created",
        created_at: str | None = None,
        updated_at: str | None = None,
        last_run_id: str | None = None,
    ) -> None:
        now = _utc_iso()
        self.id = id
        self.topic = topic
        self.status = status
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.last_run_id = last_run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_id": self.last_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectRecord:
        return cls(
            id=str(data["id"]),
            topic=str(data["topic"]),
            status=str(data.get("status") or "created"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            last_run_id=data.get("last_run_id"),
        )


class ProjectService:
    """Create / load project records and orchestrate studio sync."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        studio: StoryboardStudio | None = None,
        memory_store: ProjectMemoryStore | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else _DEFAULT_ROOT
        self._studio = studio or StoryboardStudio(
            store=StoryboardStore(root=self._root)
        )
        self._memory = memory_store or ProjectMemoryStore(root=self._root)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def studio(self) -> StoryboardStudio:
        return self._studio

    @property
    def memory_store(self) -> ProjectMemoryStore:
        return self._memory

    def path_for(self, project_id: str) -> Path:
        safe = (
            " ".join(project_id.split())
            .replace("..", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
        return self._root / safe / "project.json"

    def create(self, topic: str, *, project_id: str | None = None) -> ProjectRecord:
        cleaned = " ".join(topic.split())
        if not cleaned:
            raise ValueError("topic must be a non-empty string")
        pid = project_id or project_id_for_topic(cleaned)
        existing = self.load(pid)
        if existing is not None:
            return existing
        record = ProjectRecord(id=pid, topic=cleaned, status="created")
        self.save(record)
        return record

    def load(self, project_id: str) -> ProjectRecord | None:
        path = self.path_for(project_id)
        if not path.is_file():
            return None
        try:
            return ProjectRecord.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=project_load_failed id=%r error=%s", project_id, exc)
            return None

    def save(self, record: ProjectRecord) -> Path:
        path = self.path_for(record.id)
        record.updated_at = _utc_iso()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(record.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(path)
        return path

    def list_projects(self) -> list[ProjectRecord]:
        if not self._root.is_dir():
            return []
        records: list[ProjectRecord] = []
        for child in sorted(self._root.iterdir()):
            path = child / "project.json"
            if not path.is_file():
                continue
            try:
                records.append(
                    ProjectRecord.from_dict(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return records

    def require(self, project_id: str) -> ProjectRecord:
        record = self.load(project_id)
        if record is None:
            raise KeyError(f"Project {project_id!r} not found")
        return record

    def to_response(self, record: ProjectRecord) -> dict[str, Any]:
        board = self._studio.load(record.id)
        memory = self._memory.load(record.id)
        return {
            **record.to_dict(),
            "scene_count": len(board.scenes) if board else 0,
            "has_memory": memory is not None,
            "has_storyboard": board is not None,
        }

    def sync_studio_from_pipeline(
        self,
        result: PipelineResult,
        *,
        project_id: str,
    ) -> Storyboard:
        """Materialize / refresh a Studio storyboard from a pipeline result."""
        characters = list(result.research.key_people) if result.research else []
        board = self._studio.create_from_plan(
            result.plan,
            project_id=project_id,
            characters=characters,
            persist=False,
        )
        # Overlay prompts / images from the pipeline storyboard when present.
        by_id = {scene.id: scene for scene in result.storyboard.scenes}
        updated_scenes: list[StoryboardScene] = []
        for scene in board.scenes:
            pipe = by_id.get(scene.id)
            if pipe is None:
                updated_scenes.append(scene)
                continue
            status = SceneLifecycle.DRAFT
            if pipe.image is not None and pipe.image.url:
                status = SceneLifecycle.IMAGE_GENERATED
            elif pipe.image_prompt:
                status = SceneLifecycle.APPROVED
            updated_scenes.append(
                scene.model_copy(
                    update={
                        "image_prompt": pipe.image_prompt or scene.image_prompt,
                        "image": pipe.image,
                        "description": pipe.description or scene.description,
                        "title": pipe.title or scene.title,
                        "status": status,
                        "error": pipe.error,
                    }
                )
            )
        board = board.model_copy(
            update={
                "scenes": updated_scenes,
                "review": result.review,
                "status": SceneLifecycle.APPROVED
                if result.review and result.review.approved
                else SceneLifecycle.DRAFT,
                "metadata": {
                    "run_id": result.run_id,
                    "source": "pipeline.generate",
                },
            }
        )
        return self._studio.save(board)


def image_generator_fn(prompt: str) -> ImageResult:
    """Adapter for Studio.execute using the configured image stack."""
    from src.api.factory import _build_image_services

    generator, _storage, _stubs = _build_image_services()
    return generator.generate(prompt)


def video_generator_fn(
    prompt: str,
    *,
    source_image: str | None = None,
    duration: float | None = None,
    **kwargs: Any,
) -> VideoResult:
    """Adapter for Studio.execute using VideoRouter (architecture stub OK)."""
    from src.video import VideoEngineAdapter, VideoRouter

    router = VideoRouter.from_yaml()
    adapter = VideoEngineAdapter(router)
    return adapter.generate(
        prompt,
        source_image=source_image,
        duration=duration,
        **kwargs,
    )
