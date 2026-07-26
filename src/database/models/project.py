"""ORM model: :class:`Project`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now
from src.database.models._helpers import enum_values

if TYPE_CHECKING:
    from src.database.models.scene import Scene


class ProjectStatus(str, enum.Enum):
    """Lifecycle status for a :class:`Project`."""

    CREATED = "created"
    RUNNING = "running"
    PLAYGROUND = "playground"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class Project(Base):
    """A historical topic run managed by the director pipeline."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    topic: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ProjectStatus.CREATED,
        server_default=ProjectStatus.CREATED.value,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    scenes: Mapped[list[Scene]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Scene.scene_number",
    )

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id!r} topic={self.topic!r} "
            f"status={self.status!r}>"
        )
