"""SQLAlchemy 2.0 declarative base for AI Director.

ORM mapped classes are defined under :mod:`src.database.models` and must subclass
:class:`Base`. This module contains no business logic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for column defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for every SQLAlchemy ORM model."""
