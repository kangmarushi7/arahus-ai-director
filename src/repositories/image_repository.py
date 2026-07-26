"""Data-access layer for :class:`~src.database.models.Image`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Image, ImageStatus


class ImageRepository:
    """CRUD repository for :class:`Image` rows.

    The SQLAlchemy :class:`~sqlalchemy.orm.Session` is injected; this class
    performs persistence only and contains no domain rules.
    """

    def __init__(self, session: Session) -> None:
        """Bind this repository to ``session``.

        Args:
            session: Active SQLAlchemy session owned by the caller.
        """
        self._session = session

    def create(
        self,
        *,
        prompt_version_id: uuid.UUID,
        url: str | None = None,
        status: ImageStatus = ImageStatus.PENDING,
        error: str | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
        id: uuid.UUID | None = None,
    ) -> Image:
        """Insert a new image row and flush.

        Returns:
            The persisted :class:`Image` ORM instance.
        """
        image = Image(
            id=id or uuid.uuid4(),
            prompt_version_id=prompt_version_id,
            url=url,
            status=status,
            error=error,
            width=width,
            height=height,
            seed=seed,
        )
        self._session.add(image)
        self._session.flush()
        return image

    def get(self, image_id: uuid.UUID) -> Image | None:
        """Return an image by primary key, or ``None`` if missing."""
        return self._session.get(Image, image_id)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        prompt_version_id: uuid.UUID | None = None,
        status: ImageStatus | None = None,
    ) -> list[Image]:
        """Return images newest-first.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            prompt_version_id: Optional prompt-version filter.
            status: Optional status filter.

        Returns:
            A list of :class:`Image` instances.
        """
        stmt = select(Image).order_by(Image.created_at.desc())
        if prompt_version_id is not None:
            stmt = stmt.where(Image.prompt_version_id == prompt_version_id)
        if status is not None:
            stmt = stmt.where(Image.status == status)
        stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
        return list(self._session.scalars(stmt).all())

    def update(self, image: Image, **fields: Any) -> Image:
        """Apply ``fields`` onto ``image`` and flush.

        Args:
            image: Attached (or to-be-attached) image instance.
            **fields: Column values to set (unknown keys are ignored).

        Returns:
            The updated :class:`Image` instance.
        """
        allowed = {
            "prompt_version_id",
            "url",
            "status",
            "error",
            "width",
            "height",
            "seed",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(image, key, value)
        self._session.add(image)
        self._session.flush()
        return image

    def delete(self, image: Image) -> None:
        """Delete ``image``."""
        self._session.delete(image)
        self._session.flush()
