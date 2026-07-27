"""ORM model: :class:`CharacterAlias`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now

if TYPE_CHECKING:
    from src.database.models.character import Character


class CharacterAlias(Base):
    """Alternate name, title, or spelling for a :class:`Character`.

    Aliases are unique across the knowledge base so
    :meth:`~src.repositories.character_repository.CharacterRepository.find_by_alias`
    resolves unambiguously.
    """

    __tablename__ = "character_aliases"
    __table_args__ = (
        UniqueConstraint("alias", name="uq_character_aliases_alias"),
        Index("ix_character_aliases_character_id", "character_id"),
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
    alias: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
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

    character: Mapped[Character] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return (
            f"<CharacterAlias id={self.id!r} character_id={self.character_id!r} "
            f"alias={self.alias!r}>"
        )
