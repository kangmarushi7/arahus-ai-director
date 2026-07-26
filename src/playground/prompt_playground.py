"""Prompt playground service for iterative prompt versions and image previews.

Creates prompt versions, generates images via an injected
:class:`~src.pipeline.ImageGenerator`, persists results through repositories,
and tracks the selected version per scene. Returns Pydantic models only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field
from sqlalchemy.orm import Session

from src.database.models import Image as ImageRow
from src.database.models import ImageStatus
from src.database.models import PromptVersion as PromptVersionRow
from src.database.models import PromptVersionStatus
from src.database.session import get_session
from src.models.base import StrictModel
from src.models.image import ImageResult
from src.repositories.image_repository import ImageRepository
from src.repositories.prompt_version_repository import PromptVersionRepository
from src.repositories.scene_repository import SceneRepository

if TYPE_CHECKING:
    from src.pipeline import ImageGenerator

logger = logging.getLogger(__name__)

SessionFactory = Callable[..., AbstractContextManager[Session]]


class PromptPlaygroundError(Exception):
    """Base error for :class:`PromptPlayground` failures."""


class PromptPlaygroundNotFoundError(PromptPlaygroundError):
    """Raised when a scene or prompt version cannot be found."""


class ImageRecord(StrictModel):
    """Persisted image row returned by the playground."""

    id: uuid.UUID
    prompt_version_id: uuid.UUID
    url: str | None = None
    status: str
    error: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    seed: int | None = None
    created_at: datetime


class PromptVersionRecord(StrictModel):
    """Persisted prompt-version row returned by the playground."""

    id: uuid.UUID
    scene_id: uuid.UUID
    version: int = Field(ge=1)
    prompt: str
    model: str
    is_selected: bool = False
    created_at: datetime
    images: list[ImageRecord] = Field(default_factory=list)


class PromptPlayground:
    """Service for creating, rendering, selecting, and deleting prompt versions.

    Dependencies are injected so the playground stays testable and free of
    Streamlit or composition-root concerns. Persistence goes through
    repository classes — not raw SQLAlchemy queries in the service methods.
    """

    def __init__(
        self,
        image_generator: ImageGenerator,
        session_factory: SessionFactory | None = None,
    ) -> None:
        """Wire collaborators.

        Args:
            image_generator: Renders a prompt into an :class:`ImageResult`.
            session_factory: Context manager factory that yields a SQLAlchemy
                :class:`~sqlalchemy.orm.Session`. Defaults to
                :func:`~src.database.session.get_session`.
        """
        if image_generator is None:
            raise ValueError("image_generator is required")

        self._image_generator = image_generator
        self._session_factory: SessionFactory = session_factory or get_session

    def create_prompt_version(
        self,
        scene_id: uuid.UUID | str,
        prompt: str,
        model: str,
    ) -> PromptVersionRecord:
        """Create the next prompt version for ``scene_id``."""
        cleaned_prompt = _require_non_empty(prompt, field_name="prompt")
        cleaned_model = _require_non_empty(model, field_name="model")
        scene_pk = _parse_uuid(scene_id, field_name="scene_id")

        with self._session_factory() as session:
            scenes = SceneRepository(session)
            prompts = PromptVersionRepository(session)
            if scenes.get(scene_pk) is None:
                raise PromptPlaygroundNotFoundError(
                    f"Scene id={scene_pk} was not found"
                )

            existing = prompts.list(scene_id=scene_pk, limit=10_000)
            next_version = (max((row.version for row in existing), default=0) + 1)

            row = prompts.create(
                scene_id=scene_pk,
                prompt_text=cleaned_prompt,
                model=cleaned_model,
                version=next_version,
                status=PromptVersionStatus.DRAFT,
                is_selected=False,
            )
            session.refresh(row)
            record = _prompt_version_to_model(row)
            logger.info(
                "event=prompt_version_created scene_id=%s version_id=%s "
                "version=%s model=%r",
                scene_pk,
                row.id,
                row.version,
                cleaned_model,
            )
            return record

    def generate_image(self, prompt_version_id: uuid.UUID | str) -> ImageRecord:
        """Generate an image for ``prompt_version_id`` and persist it."""
        version_pk = _parse_uuid(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            prompts = PromptVersionRepository(session)
            images = ImageRepository(session)
            version = prompts.get(version_pk)
            if version is None:
                raise PromptPlaygroundNotFoundError(
                    f"PromptVersion id={version_pk} was not found"
                )

            prompt_text = version.prompt_text
            logger.info(
                "event=prompt_playground_generate_start version_id=%s "
                "prompt_chars=%s",
                version_pk,
                len(prompt_text),
            )

            try:
                result = self._image_generator.generate(prompt_text)
            except Exception as exc:  # noqa: BLE001 - persist failure status
                image_row = images.create(
                    prompt_version_id=version_pk,
                    url=None,
                    status=ImageStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                )
                session.refresh(image_row)
                logger.exception(
                    "event=prompt_playground_generate_failed version_id=%s",
                    version_pk,
                )
                return _image_to_model(image_row)

            if not isinstance(result, ImageResult):
                raise PromptPlaygroundError(
                    "ImageGenerator.generate must return ImageResult, got "
                    f"{type(result).__name__}"
                )

            image_row = images.create(
                prompt_version_id=version_pk,
                url=result.url,
                status=ImageStatus.OK if result.url else ImageStatus.GENERATED_NO_URL,
                error=None,
                width=result.width,
                height=result.height,
                seed=result.seed,
            )
            session.refresh(image_row)
            record = _image_to_model(image_row)
            logger.info(
                "event=prompt_playground_generate_ok version_id=%s image_id=%s "
                "url=%r",
                version_pk,
                image_row.id,
                image_row.url,
            )
            return record

    def select_version(self, prompt_version_id: uuid.UUID | str) -> PromptVersionRecord:
        """Mark ``prompt_version_id`` as the selected version for its scene."""
        version_pk = _parse_uuid(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            prompts = PromptVersionRepository(session)
            version = prompts.get(version_pk)
            if version is None:
                raise PromptPlaygroundNotFoundError(
                    f"PromptVersion id={version_pk} was not found"
                )

            siblings = prompts.list(scene_id=version.scene_id, limit=10_000)
            for sibling in siblings:
                if sibling.is_selected and sibling.id != version.id:
                    prompts.update(
                        sibling,
                        is_selected=False,
                        status=PromptVersionStatus.SUPERSEDED,
                    )

            version = prompts.update(
                version,
                is_selected=True,
                status=PromptVersionStatus.ACTIVE,
            )
            session.refresh(version)
            record = _prompt_version_to_model(version)
            logger.info(
                "event=prompt_version_selected version_id=%s scene_id=%s",
                version_pk,
                version.scene_id,
            )
            return record

    def list_versions(self, scene_id: uuid.UUID | str) -> list[PromptVersionRecord]:
        """List all prompt versions for ``scene_id`` (oldest → newest)."""
        scene_pk = _parse_uuid(scene_id, field_name="scene_id")

        with self._session_factory() as session:
            scenes = SceneRepository(session)
            prompts = PromptVersionRepository(session)
            if scenes.get(scene_pk) is None:
                raise PromptPlaygroundNotFoundError(
                    f"Scene id={scene_pk} was not found"
                )
            rows = prompts.list(scene_id=scene_pk, limit=10_000)
            return [_prompt_version_to_model(row) for row in rows]

    def delete_version(self, prompt_version_id: uuid.UUID | str) -> PromptVersionRecord:
        """Delete ``prompt_version_id`` and its cascaded images."""
        version_pk = _parse_uuid(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            prompts = PromptVersionRepository(session)
            version = prompts.get(version_pk)
            if version is None:
                raise PromptPlaygroundNotFoundError(
                    f"PromptVersion id={version_pk} was not found"
                )
            # Touch relationship so the snapshot includes images before delete.
            snapshot = _prompt_version_to_model(version)
            prompts.delete(version)
            logger.info(
                "event=prompt_version_deleted version_id=%s scene_id=%s",
                version_pk,
                snapshot.scene_id,
            )
            return snapshot


def _require_non_empty(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _parse_uuid(value: uuid.UUID | str, *, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


def _image_to_model(row: ImageRow) -> ImageRecord:
    status = row.status.value if hasattr(row.status, "value") else str(row.status)
    return ImageRecord(
        id=row.id,
        prompt_version_id=row.prompt_version_id,
        url=row.url,
        status=status,
        error=row.error,
        width=row.width,
        height=row.height,
        seed=row.seed,
        created_at=row.created_at,
    )


def _prompt_version_to_model(row: PromptVersionRow) -> PromptVersionRecord:
    images = [_image_to_model(image) for image in (row.images or [])]
    return PromptVersionRecord(
        id=row.id,
        scene_id=row.scene_id,
        version=row.version,
        prompt=row.prompt_text,
        model=row.model,
        is_selected=bool(row.is_selected),
        created_at=row.created_at,
        images=images,
    )
