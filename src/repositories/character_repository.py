"""Data-access layer for :class:`~src.database.models.Character`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.database.models import Character, CharacterAlias


class CharacterRepository:
    """CRUD and lookup repository for :class:`Character` rows.

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
        name: str,
        description: str = "",
        appearance: str = "",
        era: str | None = None,
        role: str | None = None,
        notes: str | None = None,
        id: uuid.UUID | None = None,
    ) -> Character:
        """Insert a new character and flush.

        Returns:
            The persisted :class:`Character` ORM instance.
        """
        character = Character(
            id=id or uuid.uuid4(),
            name=name,
            description=description,
            appearance=appearance,
            era=era,
            role=role,
            notes=notes,
        )
        self._session.add(character)
        self._session.flush()
        return character

    def update(self, character: Character, **fields: Any) -> Character:
        """Apply ``fields`` onto ``character`` and flush.

        Args:
            character: Attached (or to-be-attached) character instance.
            **fields: Column values to set (unknown keys are ignored).

        Returns:
            The updated :class:`Character` instance.
        """
        allowed = {
            "name",
            "description",
            "appearance",
            "era",
            "role",
            "notes",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(character, key, value)
        self._session.add(character)
        self._session.flush()
        return character

    def delete(self, character: Character) -> None:
        """Delete ``character`` (cascades to aliases, refs, scene links)."""
        self._session.delete(character)
        self._session.flush()

    def find_by_name(self, name: str) -> Character | None:
        """Return the character whose canonical ``name`` matches (case-insensitive)."""
        cleaned = name.strip()
        if not cleaned:
            return None
        stmt = (
            select(Character)
            .where(func.lower(Character.name) == cleaned.lower())
            .options(*self._default_load_options())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def find_by_alias(self, alias: str) -> Character | None:
        """Return the character linked to ``alias`` (case-insensitive)."""
        cleaned = alias.strip()
        if not cleaned:
            return None
        stmt = (
            select(Character)
            .join(CharacterAlias, CharacterAlias.character_id == Character.id)
            .where(func.lower(CharacterAlias.alias) == cleaned.lower())
            .options(*self._default_load_options())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        era: str | None = None,
    ) -> list[Character]:
        """Return characters ordered by name ascending.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            era: Optional exact era filter.

        Returns:
            A list of :class:`Character` instances.
        """
        stmt = select(Character).order_by(Character.name.asc())
        if era is not None:
            stmt = stmt.where(Character.era == era)
        stmt = (
            stmt.offset(max(0, offset))
            .limit(max(1, limit))
            .options(*self._default_load_options())
        )
        return list(self._session.scalars(stmt).unique().all())

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Character]:
        """Search characters by name, alias, description, appearance, or role.

        Matching is case-insensitive substring (``ILIKE``). Empty ``query``
        returns an empty list.

        Returns:
            Distinct :class:`Character` rows ordered by name.
        """
        cleaned = query.strip()
        if not cleaned:
            return []

        pattern = f"%{cleaned}%"
        stmt = (
            select(Character)
            .outerjoin(CharacterAlias, CharacterAlias.character_id == Character.id)
            .where(
                or_(
                    Character.name.ilike(pattern),
                    Character.description.ilike(pattern),
                    Character.appearance.ilike(pattern),
                    Character.role.ilike(pattern),
                    Character.era.ilike(pattern),
                    CharacterAlias.alias.ilike(pattern),
                )
            )
            .order_by(Character.name.asc())
            .offset(max(0, offset))
            .limit(max(1, limit))
            .options(*self._default_load_options())
        )
        return list(self._session.scalars(stmt).unique().all())

    @staticmethod
    def _default_load_options() -> tuple[Any, ...]:
        """Eager-load commonly needed collections without N+1 queries."""
        return (
            selectinload(Character.aliases),
            selectinload(Character.reference_images),
        )
