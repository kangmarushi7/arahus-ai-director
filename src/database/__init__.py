"""PostgreSQL persistence layer (SQLAlchemy 2.0).

Exports engine/session primitives and ORM models.
"""

from __future__ import annotations

from typing import Any

from src.database import session as _session
from src.database.base import Base, utc_now
from src.database.models import (
    Image,
    ImageStatus,
    Project,
    ProjectStatus,
    PromptVersion,
    PromptVersionStatus,
    Scene,
    SceneStatus,
)
from src.database.session import (
    configure_database,
    create_database,
    get_database_url,
    get_db,
    get_engine,
    get_session,
    mask_database_url,
    normalize_database_url,
    reset_engine,
)

__all__ = [
    "Base",
    "Image",
    "ImageStatus",
    "Project",
    "ProjectStatus",
    "PromptVersion",
    "PromptVersionStatus",
    "Scene",
    "SceneStatus",
    "SessionLocal",
    "configure_database",
    "create_database",
    "engine",
    "get_database_url",
    "get_db",
    "get_engine",
    "get_session",
    "mask_database_url",
    "normalize_database_url",
    "reset_engine",
    "utc_now",
]


def __getattr__(name: str) -> Any:
    """Resolve live ``engine`` / ``SessionLocal`` after configuration."""
    if name == "engine":
        return _session.engine
    if name == "SessionLocal":
        return _session.SessionLocal
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
