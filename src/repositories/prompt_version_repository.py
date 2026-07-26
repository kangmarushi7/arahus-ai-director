"""Data-access layer for :class:`~src.database.models.PromptVersion`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import PromptVersion, PromptVersionStatus


class PromptVersionRepository:
    """CRUD repository for :class:`PromptVersion` rows.

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
        scene_id: uuid.UUID,
        prompt_text: str,
        model: str = "",
        version: int = 1,
        status: PromptVersionStatus = PromptVersionStatus.DRAFT,
        is_selected: bool = False,
        id: uuid.UUID | None = None,
    ) -> PromptVersion:
        """Insert a new prompt version and flush.

        Returns:
            The persisted :class:`PromptVersion` ORM instance.
        """
        row = PromptVersion(
            id=id or uuid.uuid4(),
            scene_id=scene_id,
            version=version,
            prompt_text=prompt_text,
            model=model,
            status=status,
            is_selected=is_selected,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, prompt_version_id: uuid.UUID) -> PromptVersion | None:
        """Return a prompt version by primary key, or ``None`` if missing."""
        return self._session.get(PromptVersion, prompt_version_id)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        scene_id: uuid.UUID | None = None,
        status: PromptVersionStatus | None = None,
        is_selected: bool | None = None,
    ) -> list[PromptVersion]:
        """Return prompt versions ordered by ``version`` ascending.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            scene_id: Optional scene filter.
            status: Optional status filter.
            is_selected: Optional selection filter.

        Returns:
            A list of :class:`PromptVersion` instances.
        """
        stmt = select(PromptVersion).order_by(
            PromptVersion.scene_id,
            PromptVersion.version.asc(),
        )
        if scene_id is not None:
            stmt = stmt.where(PromptVersion.scene_id == scene_id)
        if status is not None:
            stmt = stmt.where(PromptVersion.status == status)
        if is_selected is not None:
            stmt = stmt.where(PromptVersion.is_selected.is_(is_selected))
        stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
        return list(self._session.scalars(stmt).all())

    def update(self, prompt_version: PromptVersion, **fields: Any) -> PromptVersion:
        """Apply ``fields`` onto ``prompt_version`` and flush.

        Args:
            prompt_version: Attached (or to-be-attached) instance.
            **fields: Column values to set (unknown keys are ignored).

        Returns:
            The updated :class:`PromptVersion` instance.
        """
        allowed = {
            "scene_id",
            "version",
            "prompt_text",
            "model",
            "status",
            "is_selected",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(prompt_version, key, value)
        self._session.add(prompt_version)
        self._session.flush()
        return prompt_version

    def delete(self, prompt_version: PromptVersion) -> None:
        """Delete ``prompt_version`` (cascades to images)."""
        self._session.delete(prompt_version)
        self._session.flush()
