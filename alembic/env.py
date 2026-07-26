"""Alembic migration environment (SQLAlchemy 2.0 + PostgreSQL).

Loads ``DATABASE_URL`` from the environment (via ``python-dotenv``), never from
hardcoded credentials. Autogenerate compares against
:attr:`src.database.base.Base.metadata` once ORM models are registered in
:mod:`src.database.models`.
"""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from src.database.base import Base

# Ensure mapped classes register on Base.metadata when they exist.
import src.database.models  # noqa: F401
from src.database.session import get_database_url

# Load .env / .ENV before resolving DATABASE_URL (local + CI).
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)
load_dotenv(_REPO_ROOT / ".ENV", override=False)
load_dotenv(override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure_context(**kwargs: object) -> None:
    """Apply shared autogenerate / PostgreSQL options."""
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Run migrations without a live DBAPI connection."""
    url = get_database_url()
    _configure_context(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live PostgreSQL connection."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_database_url()

    # NullPool: each migration run opens a fresh connection (production-safe
    # for short-lived CLI processes; avoids stale pooled handles on Neon).
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        _configure_context(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
