"""ORM model: :class:`Scene`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now
from src.database.models._helpers import enum_values

if TYPE_CHECKING:
    from src.database.models.project import Project
    from src.database.models.prompt_version import PromptVersion


class SceneStatus(str, enum.Enum):
    """Lifecycle status for a :class:`Scene`."""

    DRAFT = "draft"
    READY = "ready"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class Scene(Base):
    """One chronological beat belonging to a :class:`Project`."""

    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "scene_number",
            name="uq_scenes_project_number",
        ),
        Index("ix_scenes_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[SceneStatus] = mapped_column(
        Enum(
            SceneStatus,
            name="scene_status",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=SceneStatus.DRAFT,
        server_default=SceneStatus.DRAFT.value,
        index=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    project: Mapped[Project] = relationship(back_populates="scenes")
    prompt_versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PromptVersion.version",
    )

    def __repr__(self) -> str:
        return (
            f"<Scene id={self.id!r} project_id={self.project_id!r} "
            f"scene_number={self.scene_number!r} title={self.title!r}>"
        )
