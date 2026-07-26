"""Data-access layer for :class:`~src.database.models.Scene`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Scene, SceneStatus


class SceneRepository:
    """CRUD repository for :class:`Scene` rows.

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
        project_id: uuid.UUID,
        scene_number: int,
        title: str,
        description: str = "",
        status: SceneStatus = SceneStatus.DRAFT,
        error: str | None = None,
        id: uuid.UUID | None = None,
    ) -> Scene:
        """Insert a new scene and flush.

        Returns:
            The persisted :class:`Scene` ORM instance.
        """
        scene = Scene(
            id=id or uuid.uuid4(),
            project_id=project_id,
            scene_number=scene_number,
            title=title,
            description=description,
            status=status,
            error=error,
        )
        self._session.add(scene)
        self._session.flush()
        return scene

    def get(self, scene_id: uuid.UUID) -> Scene | None:
        """Return a scene by primary key, or ``None`` if missing."""
        return self._session.get(Scene, scene_id)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        project_id: uuid.UUID | None = None,
        status: SceneStatus | None = None,
    ) -> list[Scene]:
        """Return scenes ordered by project then ``scene_number``.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            project_id: Optional project filter.
            status: Optional status filter.

        Returns:
            A list of :class:`Scene` instances.
        """
        stmt = select(Scene).order_by(Scene.project_id, Scene.scene_number.asc())
        if project_id is not None:
            stmt = stmt.where(Scene.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Scene.status == status)
        stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
        return list(self._session.scalars(stmt).all())

    def update(self, scene: Scene, **fields: Any) -> Scene:
        """Apply ``fields`` onto ``scene`` and flush.

        Args:
            scene: Attached (or to-be-attached) scene instance.
            **fields: Column values to set (unknown keys are ignored).

        Returns:
            The updated :class:`Scene` instance.
        """
        allowed = {
            "project_id",
            "scene_number",
            "title",
            "description",
            "status",
            "error",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(scene, key, value)
        self._session.add(scene)
        self._session.flush()
        return scene

    def delete(self, scene: Scene) -> None:
        """Delete ``scene`` (cascades to prompt versions / images)."""
        self._session.delete(scene)
        self._session.flush()
