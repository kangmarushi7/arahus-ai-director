"""ORM model: :class:`PromptVersion`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now
from src.database.models._helpers import enum_values

if TYPE_CHECKING:
    from src.database.models.image import Image
    from src.database.models.scene import Scene


class PromptVersionStatus(str, enum.Enum):
    """Lifecycle status for a :class:`PromptVersion`."""

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class PromptVersion(Base):
    """A versioned image prompt for a :class:`Scene`."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "version",
            name="uq_prompt_versions_scene_version",
        ),
        Index("ix_prompt_versions_scene_selected", "scene_id", "is_selected"),
        Index("ix_prompt_versions_scene_status", "scene_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="",
        server_default="",
        index=True,
    )
    status: Mapped[PromptVersionStatus] = mapped_column(
        Enum(
            PromptVersionStatus,
            name="prompt_version_status",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=PromptVersionStatus.DRAFT,
        server_default=PromptVersionStatus.DRAFT.value,
        index=True,
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
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

    scene: Mapped[Scene] = relationship(back_populates="prompt_versions")
    images: Mapped[list[Image]] = relationship(
        back_populates="prompt_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Image.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<PromptVersion id={self.id!r} scene_id={self.scene_id!r} "
            f"version={self.version!r} status={self.status!r} "
            f"is_selected={self.is_selected!r}>"
        )
