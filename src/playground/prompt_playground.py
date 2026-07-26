"""Prompt playground service for iterative prompt versions and image previews.

Creates prompt versions, generates images via an injected
:class:`~src.pipeline.ImageGenerator`, persists results, and tracks the
selected version per scene. Returns Pydantic models only — no UI code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.database.database import Image as ImageRow
from src.database.database import PromptVersion as PromptVersionRow
from src.database.database import Scene as SceneRow
from src.database.database import get_session
from src.models.base import StrictModel
from src.models.image import ImageResult

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

    id: int
    prompt_version_id: int
    url: str | None = None
    status: str
    error: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    seed: int | None = None
    created_at: datetime


class PromptVersionRecord(StrictModel):
    """Persisted prompt-version row returned by the playground."""

    id: int
    scene_id: int
    version: int = Field(ge=1)
    prompt: str
    model: str
    is_selected: bool = False
    created_at: datetime
    images: list[ImageRecord] = Field(default_factory=list)


class PromptPlayground:
    """Service for creating, rendering, selecting, and deleting prompt versions.

    Dependencies are injected so the playground stays testable and free of
    Streamlit or composition-root concerns.
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
                :func:`~src.database.database.get_session`.
        """
        if image_generator is None:
            raise ValueError("image_generator is required")

        self._image_generator = image_generator
        self._session_factory: SessionFactory = session_factory or get_session

    def create_prompt_version(
        self,
        scene_id: int,
        prompt: str,
        model: str,
    ) -> PromptVersionRecord:
        """Create the next prompt version for ``scene_id``.

        Args:
            scene_id: Existing scene primary key.
            prompt: Image-prompt text for this version.
            model: Model identifier used to author or target the prompt.

        Returns:
            The newly created :class:`PromptVersionRecord`.

        Raises:
            ValueError: If ``prompt`` or ``model`` is empty.
            PromptPlaygroundNotFoundError: If the scene does not exist.
        """
        cleaned_prompt = _require_non_empty(prompt, field_name="prompt")
        cleaned_model = _require_non_empty(model, field_name="model")
        scene_pk = _require_positive_id(scene_id, field_name="scene_id")

        with self._session_factory() as session:
            scene = session.get(SceneRow, scene_pk)
            if scene is None:
                raise PromptPlaygroundNotFoundError(
                    f"Scene id={scene_pk} was not found"
                )

            next_version = (
                session.scalar(
                    select(func.coalesce(func.max(PromptVersionRow.version), 0)).where(
                        PromptVersionRow.scene_id == scene_pk
                    )
                )
                or 0
            ) + 1

            row = PromptVersionRow(
                scene_id=scene_pk,
                version=next_version,
                prompt_text=cleaned_prompt,
                model=cleaned_model,
                is_selected=False,
            )
            session.add(row)
            session.flush()
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

    def generate_image(self, prompt_version_id: int) -> ImageRecord:
        """Generate an image for ``prompt_version_id`` and persist it.

        On generator failure, a ``failed`` image row is still stored and
        returned so the UI can show the error without losing history.

        Args:
            prompt_version_id: Prompt-version primary key.

        Returns:
            The stored :class:`ImageRecord`.

        Raises:
            PromptPlaygroundNotFoundError: If the prompt version does not exist.
            PromptPlaygroundError: If the generator returns an invalid type.
        """
        version_pk = _require_positive_id(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            version = session.get(PromptVersionRow, version_pk)
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
                image_row = ImageRow(
                    prompt_version_id=version_pk,
                    url=None,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                session.add(image_row)
                session.flush()
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

            image_row = ImageRow(
                prompt_version_id=version_pk,
                url=result.url,
                status="ok" if result.url else "generated_no_url",
                error=None,
                width=result.width,
                height=result.height,
                seed=result.seed,
            )
            session.add(image_row)
            session.flush()
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

    def select_version(self, prompt_version_id: int) -> PromptVersionRecord:
        """Mark ``prompt_version_id`` as the selected version for its scene.

        Clears ``is_selected`` on sibling versions for the same scene.

        Args:
            prompt_version_id: Prompt-version primary key to select.

        Returns:
            The updated :class:`PromptVersionRecord` including images.

        Raises:
            PromptPlaygroundNotFoundError: If the prompt version does not exist.
        """
        version_pk = _require_positive_id(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            version = session.scalar(
                select(PromptVersionRow)
                .where(PromptVersionRow.id == version_pk)
                .options(selectinload(PromptVersionRow.images))
            )
            if version is None:
                raise PromptPlaygroundNotFoundError(
                    f"PromptVersion id={version_pk} was not found"
                )

            siblings = session.scalars(
                select(PromptVersionRow).where(
                    PromptVersionRow.scene_id == version.scene_id
                )
            ).all()
            for sibling in siblings:
                sibling.is_selected = sibling.id == version_pk

            session.flush()
            session.refresh(version)
            record = _prompt_version_to_model(version)
            logger.info(
                "event=prompt_version_selected version_id=%s scene_id=%s",
                version_pk,
                version.scene_id,
            )
            return record

    def list_versions(self, scene_id: int) -> list[PromptVersionRecord]:
        """List all prompt versions for ``scene_id`` (oldest → newest).

        Args:
            scene_id: Scene primary key.

        Returns:
            Ordered list of :class:`PromptVersionRecord` objects with images.

        Raises:
            PromptPlaygroundNotFoundError: If the scene does not exist.
        """
        scene_pk = _require_positive_id(scene_id, field_name="scene_id")

        with self._session_factory() as session:
            scene = session.get(SceneRow, scene_pk)
            if scene is None:
                raise PromptPlaygroundNotFoundError(
                    f"Scene id={scene_pk} was not found"
                )

            rows = session.scalars(
                select(PromptVersionRow)
                .where(PromptVersionRow.scene_id == scene_pk)
                .options(selectinload(PromptVersionRow.images))
                .order_by(PromptVersionRow.version.asc())
            ).all()
            return [_prompt_version_to_model(row) for row in rows]

    def delete_version(self, prompt_version_id: int) -> PromptVersionRecord:
        """Delete ``prompt_version_id`` and its cascaded images.

        Args:
            prompt_version_id: Prompt-version primary key.

        Returns:
            A snapshot of the deleted :class:`PromptVersionRecord`.

        Raises:
            PromptPlaygroundNotFoundError: If the prompt version does not exist.
        """
        version_pk = _require_positive_id(
            prompt_version_id,
            field_name="prompt_version_id",
        )

        with self._session_factory() as session:
            version = session.scalar(
                select(PromptVersionRow)
                .where(PromptVersionRow.id == version_pk)
                .options(selectinload(PromptVersionRow.images))
            )
            if version is None:
                raise PromptPlaygroundNotFoundError(
                    f"PromptVersion id={version_pk} was not found"
                )

            snapshot = _prompt_version_to_model(version)
            session.delete(version)
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


def _require_positive_id(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _image_to_model(row: ImageRow) -> ImageRecord:
    return ImageRecord(
        id=row.id,
        prompt_version_id=row.prompt_version_id,
        url=row.url,
        status=row.status,
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
