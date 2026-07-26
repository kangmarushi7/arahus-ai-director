"""Data-access layer for :class:`~src.database.models.Project`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Project, ProjectStatus


class ProjectRepository:
    """CRUD repository for :class:`Project` rows.

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
        topic: str,
        status: ProjectStatus = ProjectStatus.CREATED,
        notes: str | None = None,
        id: uuid.UUID | None = None,
    ) -> Project:
        """Insert a new project and flush.

        Args:
            topic: Historical topic label.
            status: Project lifecycle status.
            notes: Optional free-form notes.
            id: Optional explicit primary key (defaults to a new UUID).

        Returns:
            The persisted :class:`Project` ORM instance.
        """
        project = Project(
            id=id or uuid.uuid4(),
            topic=topic,
            status=status,
            notes=notes,
        )
        self._session.add(project)
        self._session.flush()
        return project

    def get(self, project_id: uuid.UUID) -> Project | None:
        """Return a project by primary key, or ``None`` if missing."""
        return self._session.get(Project, project_id)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: ProjectStatus | None = None,
    ) -> list[Project]:
        """Return projects newest-first.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            status: Optional status filter.

        Returns:
            A list of :class:`Project` instances.
        """
        stmt = select(Project).order_by(Project.created_at.desc())
        if status is not None:
            stmt = stmt.where(Project.status == status)
        stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
        return list(self._session.scalars(stmt).all())

    def update(self, project: Project, **fields: Any) -> Project:
        """Apply ``fields`` onto ``project`` and flush.

        Args:
            project: Attached (or to-be-attached) project instance.
            **fields: Column values to set (unknown keys are ignored).

        Returns:
            The updated :class:`Project` instance.
        """
        allowed = {"topic", "status", "notes"}
        for key, value in fields.items():
            if key in allowed:
                setattr(project, key, value)
        self._session.add(project)
        self._session.flush()
        return project

    def delete(self, project: Project) -> None:
        """Delete ``project`` (cascades to scenes / prompts / images)."""
        self._session.delete(project)
        self._session.flush()
