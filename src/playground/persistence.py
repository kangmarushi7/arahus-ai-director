"""Persist storyboard scenes into SQLite for the prompt playground."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.database import Image as ImageRow
from src.database.database import Project
from src.database.database import PromptVersion as PromptVersionRow
from src.database.database import Scene as SceneRow
from src.database.database import create_database, get_session
from src.models.pipeline import PipelineResult

logger = logging.getLogger(__name__)


def ensure_database() -> None:
    """Create the SQLite schema when missing."""
    create_database()


def sync_storyboard_project(
    topic: str,
    scenes: list[Mapping[str, Any]],
    *,
    project_id: int | None = None,
    image_model: str = "stabilityai/sdxl-turbo",
) -> tuple[int, dict[int, int]]:
    """Upsert a project + scenes for playground editing.

    Args:
        topic: Project topic label.
        scenes: Storyboard scene dicts with ``id``, ``title``, ``description``,
            and optional ``image_prompt`` / ``image``.
        project_id: Existing project to update; creates a new one when omitted.
        image_model: Model label stored on the initial prompt version.

    Returns:
        ``(project_id, {storyboard_scene_id: db_scene_id})``.
    """
    ensure_database()
    cleaned_topic = " ".join(str(topic).split()) or "Untitled project"
    mapping: dict[int, int] = {}

    with get_session() as session:
        project: Project | None = None
        if project_id is not None:
            project = session.get(Project, project_id)

        if project is None:
            project = Project(topic=cleaned_topic, status="playground")
            session.add(project)
            session.flush()
        else:
            project.topic = cleaned_topic
            project.status = "playground"

        existing_by_number = {
            scene.scene_number: scene
            for scene in session.scalars(
                select(SceneRow)
                .where(SceneRow.project_id == project.id)
                .options(
                    selectinload(SceneRow.prompt_versions).selectinload(
                        PromptVersionRow.images
                    )
                )
            ).all()
        }

        for raw in scenes:
            scene_number = int(raw.get("id") or 0)
            if scene_number < 1:
                continue

            title = str(raw.get("title") or f"Scene {scene_number}")
            description = str(raw.get("description") or "")
            prompt = str(raw.get("image_prompt") or description or title).strip()
            image_payload = raw.get("image") if isinstance(raw.get("image"), dict) else {}
            image_url = None
            if isinstance(image_payload, dict):
                image_url = image_payload.get("url")
            # Prefer pipeline GeneratedImageInfo style if present on a parallel list —
            # callers may also pass url at the top level.
            if not image_url:
                image_url = raw.get("url")

            scene = existing_by_number.get(scene_number)
            if scene is None:
                scene = SceneRow(
                    project_id=project.id,
                    scene_number=scene_number,
                    title=title,
                    description=description,
                )
                session.add(scene)
                session.flush()
            else:
                scene.title = title
                scene.description = description

            mapping[scene_number] = scene.id

            if prompt and not scene.prompt_versions:
                version = PromptVersionRow(
                    scene_id=scene.id,
                    version=1,
                    prompt_text=prompt,
                    model=image_model,
                    is_selected=True,
                )
                session.add(version)
                session.flush()
                if isinstance(image_url, str) and image_url.strip():
                    session.add(
                        ImageRow(
                            prompt_version_id=version.id,
                            url=image_url.strip(),
                            status="ok",
                        )
                    )

        session.flush()
        project_pk = int(project.id)
        logger.info(
            "event=storyboard_synced project_id=%s scenes=%s",
            project_pk,
            mapping,
        )
        return project_pk, mapping


def sync_pipeline_result(
    result: PipelineResult,
    *,
    project_id: int | None = None,
    image_model: str = "stabilityai/sdxl-turbo",
) -> tuple[int, dict[int, int]]:
    """Persist a completed pipeline storyboard for per-scene playground edits."""
    url_by_scene = {
        int(item.scene_id): item.url
        for item in result.images
        if item.url
    }
    scenes: list[dict[str, Any]] = []
    for scene in result.storyboard.scenes:
        payload = scene.model_dump(mode="json")
        if scene.id in url_by_scene and not (payload.get("image") or {}).get("url"):
            payload["url"] = url_by_scene[scene.id]
        scenes.append(payload)
    return sync_storyboard_project(
        result.topic,
        scenes,
        project_id=project_id,
        image_model=image_model,
    )
