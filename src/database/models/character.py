"""ORM model: :class:`Character`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now

if TYPE_CHECKING:
    from src.database.models.character_alias import CharacterAlias
    from src.database.models.character_reference_image import CharacterReferenceImage
    from src.database.models.scene_character import SceneCharacter


class Character(Base):
    """A named historical (or fictional) figure in the knowledge base.

    Used for visual consistency across scenes: appearance text and reference
    images feed prompt construction; aliases support lookup under alternate
    spellings and titles.
    """

    __tablename__ = "characters"
    __table_args__ = (
        Index("ix_characters_name_created_at", "name", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        unique=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Visual description used when building image prompts.",
    )
    era: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    role: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
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

    reference_images: Mapped[list[CharacterReferenceImage]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterReferenceImage.sort_order",
    )
    aliases: Mapped[list[CharacterAlias]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CharacterAlias.alias",
    )
    scene_appearances: Mapped[list[SceneCharacter]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Character id={self.id!r} name={self.name!r}>"
