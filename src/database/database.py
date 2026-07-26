"""SQLAlchemy ORM persistence for AI Director projects.

SQLite file (project root)::

    database/director.db

Hierarchy::

    Project → Scene → PromptVersion → Image
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

logger = logging.getLogger(__name__)

# Project root is two levels above this file: src/database/database.py → repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = _PROJECT_ROOT / "database" / "director.db"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this module."""


class Project(Base):
    """A historical topic run managed by the director pipeline."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="created",
        server_default="created",
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    scenes: Mapped[list[Scene]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Scene.scene_number",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id!r} topic={self.topic!r} status={self.status!r}>"


class Scene(Base):
    """One chronological beat belonging to a :class:`Project`."""

    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint("project_id", "scene_number", name="uq_scenes_project_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    project: Mapped[Project] = relationship(back_populates="scenes")
    prompt_versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Scene id={self.id!r} project_id={self.project_id!r} "
            f"scene_number={self.scene_number!r} title={self.title!r}>"
        )


class PromptVersion(Base):
    """A versioned image prompt for a :class:`Scene`."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "version",
            name="uq_prompt_versions_scene_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(
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
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )

    scene: Mapped[Scene] = relationship(back_populates="prompt_versions")
    images: Mapped[list[Image]] = relationship(
        back_populates="prompt_version",
        cascade="all, delete-orphan",
        order_by="Image.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<PromptVersion id={self.id!r} scene_id={self.scene_id!r} "
            f"version={self.version!r} model={self.model!r} "
            f"is_selected={bool(self.is_selected)!r}>"
        )


class Image(Base):
    """A rendered image produced from a :class:`PromptVersion`."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_version_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )

    prompt_version: Mapped[PromptVersion] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return (
            f"<Image id={self.id!r} prompt_version_id={self.prompt_version_id!r} "
            f"status={self.status!r} url={self.url!r}>"
        )


def get_database_path(db_path: str | Path | None = None) -> Path:
    """Resolve the SQLite file path (defaults to ``database/director.db``)."""
    if db_path is None:
        return DEFAULT_DATABASE_PATH
    return Path(db_path).expanduser().resolve()


def get_engine(
    db_path: str | Path | None = None,
    *,
    echo: bool = False,
) -> Engine:
    """Return a process-wide SQLAlchemy engine for the SQLite database.

    Args:
        db_path: Optional override for the SQLite file location.
        echo: When ``True``, log SQL statements (useful in development).

    Returns:
        A shared :class:`~sqlalchemy.engine.Engine` instance.
    """
    global _engine, _SessionLocal

    path = get_database_path(db_path)
    url = f"sqlite:///{path.as_posix()}"

    if _engine is not None and str(_engine.url) == url:
        return _engine

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    _configure_sqlite(engine)

    _engine = engine
    _SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
        class_=Session,
    )
    logger.info("event=database_engine_ready url=%s", url)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    """Enable foreign-key enforcement for SQLite connections."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_database(
    db_path: str | Path | None = None,
    *,
    echo: bool = False,
) -> Path:
    """Create the SQLite file and all ORM tables if they do not exist.

    Args:
        db_path: Optional override for the SQLite file location.
        echo: When ``True``, log SQL statements.

    Returns:
        The resolved path to ``director.db``.
    """
    path = get_database_path(db_path)
    engine = get_engine(path, echo=echo)
    Base.metadata.create_all(bind=engine)
    logger.info("event=database_created path=%s", path)
    return path


@contextmanager
def get_session(
    db_path: str | Path | None = None,
    *,
    echo: bool = False,
) -> Iterator[Session]:
    """Yield a SQLAlchemy session and commit/rollback safely.

    Usage::

        with get_session() as session:
            session.add(Project(topic="Fall of Constantinople"))

    Args:
        db_path: Optional override for the SQLite file location.
        echo: When ``True``, log SQL statements for a freshly created engine.

    Yields:
        An open :class:`~sqlalchemy.orm.Session`.
    """
    global _SessionLocal

    if _SessionLocal is None:
        get_engine(db_path, echo=echo)

    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose the shared engine (primarily for tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
