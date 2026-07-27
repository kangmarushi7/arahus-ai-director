"""Persist storyboard scenes into PostgreSQL for the prompt playground."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Mapping

from src.characters import names_mentioned_in_text
from src.database.models import ImageStatus, ProjectStatus, SceneCharacter
from src.database.session import create_database, get_session
from src.models.pipeline import PipelineResult
from src.monitoring.metrics import STAGE_DATABASE
from src.monitoring.profiler import measure_stage
from src.repositories.character_repository import CharacterRepository
from src.repositories.image_repository import ImageRepository
from src.repositories.project_repository import ProjectRepository
from src.repositories.prompt_version_repository import PromptVersionRepository
from src.repositories.scene_repository import SceneRepository

logger = logging.getLogger(__name__)


def ensure_database() -> None:
    """Create ORM tables when missing (prefer Alembic in production)."""
    create_database()


def sync_storyboard_project(
    topic: str,
    scenes: list[Mapping[str, Any]],
    *,
    project_id: uuid.UUID | str | None = None,
    image_model: str = "black-forest-labs/FLUX.1-dev",
) -> tuple[uuid.UUID, dict[int, uuid.UUID]]:
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
    mapping: dict[int, uuid.UUID] = {}
    existing_id = _parse_uuid(project_id) if project_id is not None else None

    with get_session() as session:
        projects = ProjectRepository(session)
        scenes_repo = SceneRepository(session)
        prompts = PromptVersionRepository(session)
        images = ImageRepository(session)

        project = projects.get(existing_id) if existing_id is not None else None
        if project is None:
            project = projects.create(
                topic=cleaned_topic,
                status=ProjectStatus.PLAYGROUND,
            )
        else:
            projects.update(
                project,
                topic=cleaned_topic,
                status=ProjectStatus.PLAYGROUND,
            )

        existing_scenes = {
            row.scene_number: row
            for row in scenes_repo.list(project_id=project.id, limit=10_000)
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
            if not image_url:
                image_url = raw.get("url")

            scene = existing_scenes.get(scene_number)
            if scene is None:
                scene = scenes_repo.create(
                    project_id=project.id,
                    scene_number=scene_number,
                    title=title,
                    description=description,
                )
                existing_scenes[scene_number] = scene
            else:
                scenes_repo.update(
                    scene,
                    title=title,
                    description=description,
                )

            mapping[scene_number] = scene.id

            if prompt and not scene.prompt_versions:
                version = prompts.create(
                    scene_id=scene.id,
                    prompt_text=prompt,
                    model=image_model,
                    version=1,
                    is_selected=True,
                )
                if isinstance(image_url, str) and image_url.strip():
                    images.create(
                        prompt_version_id=version.id,
                        url=image_url.strip(),
                        status=ImageStatus.OK,
                    )

        logger.info(
            "event=storyboard_synced project_id=%s scenes=%s",
            project.id,
            mapping,
        )
        return project.id, mapping


def sync_pipeline_result(
    result: PipelineResult,
    *,
    project_id: uuid.UUID | str | None = None,
    image_model: str = "black-forest-labs/FLUX.1-dev",
    metrics: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, dict[int, uuid.UUID]]:
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

    with measure_stage(STAGE_DATABASE):
        synced_id, mapping = sync_storyboard_project(
            result.topic,
            scenes,
            project_id=project_id,
            image_model=image_model,
        )
        _write_project_metrics(synced_id, metrics)
        _link_scene_characters(result, mapping)
        return synced_id, mapping


def _write_project_metrics(
    project_id: uuid.UUID,
    metrics: dict[str, Any] | None,
) -> None:
    """Best-effort write of metrics JSON onto the project row."""
    if not metrics:
        return
    try:
        with get_session() as session:
            projects = ProjectRepository(session)
            project = projects.get(project_id)
            if project is None:
                return
            if not hasattr(project, "metrics_json"):
                return
            projects.update(
                project,
                metrics_json=json.dumps(metrics, ensure_ascii=False, default=str),
            )
    except Exception as exc:  # noqa: BLE001 - optional persistence
        logger.warning("event=project_metrics_persist_skipped error=%s", exc)


def _link_scene_characters(
    result: PipelineResult,
    mapping: dict[int, uuid.UUID],
) -> None:
    """Best-effort link characters mentioned in scene text to synced scenes."""
    candidate_names = _candidate_character_names(result)
    if not candidate_names or not mapping:
        return
    try:
        with get_session() as session:
            characters = CharacterRepository(session)
            for scene in result.storyboard.scenes:
                db_scene_id = mapping.get(int(scene.id))
                if db_scene_id is None:
                    continue
                text = " ".join(
                    part
                    for part in (
                        scene.title,
                        scene.description,
                        scene.image_prompt or "",
                    )
                    if part
                )
                mentioned = names_mentioned_in_text(text, candidate_names)
                for sort_order, name in enumerate(mentioned):
                    try:
                        character = characters.find_by_name(name) or characters.find_by_alias(
                            name
                        )
                        if character is None:
                            continue
                        with session.begin_nested():
                            session.add(
                                SceneCharacter(
                                    scene_id=db_scene_id,
                                    character_id=character.id,
                                    sort_order=sort_order,
                                )
                            )
                            session.flush()
                    except Exception as exc:  # noqa: BLE001 - skip duplicates / races
                        logger.debug(
                            "event=scene_character_link_skipped scene_id=%s "
                            "name=%r error=%s",
                            db_scene_id,
                            name,
                            exc,
                        )
    except Exception as exc:  # noqa: BLE001 - optional persistence
        logger.warning("event=scene_character_link_failed error=%s", exc)


def _candidate_character_names(result: PipelineResult) -> list[str]:
    """Collect unique character names from research and character bible."""
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        cleaned = " ".join(str(raw).split())
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(cleaned)

    for person in result.research.key_people:
        _add(person)

    bible = (result.character_bible or "").strip()
    if bible:
        for line in bible.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            body = stripped[2:]
            name_part = body.split(":", 1)[0].strip()
            _add(name_part)

    return names


def _parse_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
