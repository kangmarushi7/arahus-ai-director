"""ORM model: :class:`CharacterReferenceImage`."""

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
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now

if TYPE_CHECKING:
    from src.database.models.character import Character


class CharacterReferenceImage(Base):
    """A reference image used to keep a :class:`Character` visually consistent."""

    __tablename__ = "character_reference_images"
    __table_args__ = (
        Index(
            "ix_character_reference_images_character_primary",
            "character_id",
            "is_primary",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
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
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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

    character: Mapped[Character] = relationship(back_populates="reference_images")

    def __repr__(self) -> str:
        return (
            f"<CharacterReferenceImage id={self.id!r} "
            f"character_id={self.character_id!r} is_primary={self.is_primary!r}>"
        )
