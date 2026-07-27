"""ORM model: :class:`SceneCharacter`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
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

if TYPE_CHECKING:
    from src.database.models.character import Character
    from src.database.models.scene import Scene


class SceneCharacter(Base):
    """Association of a :class:`Character` appearing in a :class:`Scene`.

    Many-to-many bridge with per-appearance metadata (role, sort order).
    """

    __tablename__ = "scene_characters"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "character_id",
            name="uq_scene_characters_scene_character",
        ),
        Index("ix_scene_characters_character_id", "character_id"),
        Index("ix_scene_characters_scene_sort", "scene_id", "sort_order"),
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
    character_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_in_scene: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
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

    scene: Mapped[Scene] = relationship(back_populates="scene_characters")
    character: Mapped[Character] = relationship(back_populates="scene_appearances")

    def __repr__(self) -> str:
        return (
            f"<SceneCharacter id={self.id!r} scene_id={self.scene_id!r} "
            f"character_id={self.character_id!r}>"
        )
