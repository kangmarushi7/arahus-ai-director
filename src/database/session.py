"""SQLAlchemy 2.0 engine and session factory for PostgreSQL.

Reads ``DATABASE_URL`` from the environment (via ``python-dotenv``). Supports
Neon and other PostgreSQL providers. Credentials are never hardcoded.

Public surface:
    * ``engine`` – shared :class:`~sqlalchemy.engine.Engine`
    * ``SessionLocal`` – :class:`~sqlalchemy.orm.sessionmaker` bound to ``engine``
    * :func:`get_session` – context manager / dependency that yields a session
    * :func:`configure_database` – injectable re-bind for tests and workers
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# Load process env first, then optional local files (never commit secrets).
load_dotenv()
load_dotenv(dotenv_path=Path(".env"), override=False)
load_dotenv(dotenv_path=Path(".ENV"), override=False)

_engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker[Session]] = None

# Populated by :func:`configure_database` (and on first :func:`get_session`).
engine: Optional[Engine] = None


def normalize_database_url(url: str) -> str:
    """Normalize a PostgreSQL URL for SQLAlchemy + psycopg (v3).

    Args:
        url: Raw connection string (``postgres://`` or ``postgresql://``).

    Returns:
        A SQLAlchemy URL using the ``postgresql+psycopg`` driver when no
        explicit driver was provided.

    Raises:
        ValueError: If ``url`` is empty.
    """
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("DATABASE_URL must be a non-empty string")

    if cleaned.startswith("postgres://"):
        cleaned = "postgresql://" + cleaned[len("postgres://") :]

    if cleaned.startswith("postgresql://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgresql://") :]

    return cleaned


def mask_database_url(url: str) -> str:
    """Return a log-safe URL with the password redacted.

    Args:
        url: Database URL that may contain credentials.

    Returns:
        The same URL with the password replaced by ``***``.
    """
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return re.sub(r":([^:@/]+)@", ":***@", url)


def get_database_url(*, database_url: Optional[str] = None) -> str:
    """Resolve ``DATABASE_URL`` from an override or the environment.

    Args:
        database_url: Optional explicit URL (injected by callers/tests).

    Returns:
        A normalized SQLAlchemy connection URL.

    Raises:
        RuntimeError: If no URL is available.
        ValueError: If an explicit override is empty.
    """
    if database_url is not None:
        raw = database_url.strip()
        if not raw:
            raise ValueError("database_url must be a non-empty string")
        return normalize_database_url(raw)

    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    return normalize_database_url(raw)


def configure_database(
    *,
    database_url: Optional[str] = None,
    echo: bool = False,
    pool_pre_ping: bool = True,
    pool_recycle: int = 300,
) -> Engine:
    """Create (or replace) the process-wide engine and session factory.

    Intended for dependency injection in tests and worker processes.

    Args:
        database_url: Optional URL override; defaults to ``DATABASE_URL``.
        echo: When ``True``, log SQL statements. Defaults to ``False``.
        pool_pre_ping: Disconnect detection before checkout. Defaults to ``True``.
        pool_recycle: Recycle connections after this many seconds. Defaults to
            ``300`` (important for Neon and other managed Postgres hosts).

    Returns:
        The configured :class:`~sqlalchemy.engine.Engine`.
    """
    global _engine, engine, SessionLocal

    url = get_database_url(database_url=database_url)
    target = make_url(url)

    if _engine is not None and _engine.url == target:
        engine = _engine
        return _engine

    if _engine is not None:
        _engine.dispose()

    created = create_engine(
        url,
        echo=echo,
        future=True,
        pool_pre_ping=pool_pre_ping,
        pool_recycle=pool_recycle,
    )
    factory: sessionmaker[Session] = sessionmaker(
        bind=created,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
        class_=Session,
    )

    _engine = created
    engine = created
    SessionLocal = factory
    logger.info(
        "event=database_engine_ready url=%s pool_recycle=%s",
        mask_database_url(url),
        pool_recycle,
    )
    return created


def get_engine(*, database_url: Optional[str] = None, echo: bool = False) -> Engine:
    """Return the shared engine, configuring it on first use.

    Args:
        database_url: Optional URL override used when the engine is first built.
        echo: SQL echo flag applied when configuring a new engine.

    Returns:
        The process-wide :class:`~sqlalchemy.engine.Engine`.
    """
    if engine is not None and database_url is None:
        return engine
    return configure_database(database_url=database_url, echo=echo)


@contextmanager
def get_session(
    *,
    session_factory: Optional[sessionmaker[Session]] = None,
    database_url: Optional[str] = None,
) -> Iterator[Session]:
    """Yield a SQLAlchemy session and commit/rollback safely.

    Dependency-injectable: pass ``session_factory`` to use a custom
    :class:`~sqlalchemy.orm.sessionmaker` (e.g. in tests).

    Usage::

        with get_session() as session:
            ...

    Args:
        session_factory: Optional injected session factory. Defaults to
            :data:`SessionLocal`.
        database_url: Optional URL used when the default engine is not yet
            configured.

    Yields:
        An open :class:`~sqlalchemy.orm.Session`.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is missing when configuration is needed.
    """
    factory = session_factory
    if factory is None:
        if SessionLocal is None:
            configure_database(database_url=database_url, echo=False)
        assert SessionLocal is not None
        factory = SessionLocal

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI-style dependency that yields a session.

    Equivalent to iterating :func:`get_session` without an explicit
    ``with`` block at the call site.

    Yields:
        An open :class:`~sqlalchemy.orm.Session`.
    """
    with get_session() as session:
        yield session


def create_database(*, database_url: Optional[str] = None) -> str:
    """Create all tables registered on :class:`~src.database.base.Base`.

    Prefer Alembic migrations in production. This helper is for bootstrap/tests.

    Args:
        database_url: Optional URL override.

    Returns:
        A masked database URL string suitable for logging.
    """
    from src.database.base import Base

    # Import models package so mapped classes register on Base.metadata.
    import src.database.models  # noqa: F401

    url = get_database_url(database_url=database_url)
    bound = configure_database(database_url=url, echo=False)
    Base.metadata.create_all(bind=bound)
    masked = mask_database_url(url)
    logger.info("event=database_schema_ready url=%s", masked)
    return masked


def reset_engine() -> None:
    """Dispose the shared engine (tests / worker restarts)."""
    global _engine, engine, SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    engine = None
    SessionLocal = None
