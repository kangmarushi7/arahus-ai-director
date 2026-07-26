"""CLI wrappers for Alembic migration commands.

Uses ``DATABASE_URL`` from the environment. Examples::

    python -m scripts.db current
    python -m scripts.db history
    python -m scripts.db revision -m "add projects" --autogenerate
    python -m scripts.db upgrade head
    python -m scripts.db downgrade -1
    python -m scripts.db stamp head
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)
    load_dotenv(_REPO_ROOT / ".ENV", override=False)
    load_dotenv(override=False)


def _run_alembic(args: list[str]) -> int:
    command = [sys.executable, "-m", "alembic", *args]
    completed = subprocess.run(command, cwd=_REPO_ROOT, check=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and forward to Alembic."""
    _load_env()

    parser = argparse.ArgumentParser(
        prog="python -m scripts.db",
        description="Alembic migration helpers for AI Director (PostgreSQL).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("current", help="Show the current revision.")
    sub.add_parser("history", help="Show revision history.")
    sub.add_parser("heads", help="Show head revisions.")

    upgrade = sub.add_parser("upgrade", help="Upgrade to a revision (default: head).")
    upgrade.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Target revision (default: head).",
    )

    downgrade = sub.add_parser("downgrade", help="Downgrade to a revision.")
    downgrade.add_argument(
        "revision",
        help="Target revision (e.g. -1, base, or a revision id).",
    )

    revision = sub.add_parser(
        "revision",
        help="Create a new revision (use --autogenerate after adding models).",
    )
    revision.add_argument("-m", "--message", required=True, help="Revision message.")
    revision.add_argument(
        "--autogenerate",
        action="store_true",
        help="Autogenerate from SQLAlchemy metadata.",
    )
    revision.add_argument(
        "--empty",
        action="store_true",
        help="Force an empty revision (no autogenerate).",
    )

    stamp = sub.add_parser(
        "stamp",
        help="Set revision without running migrations (bootstrap only).",
    )
    stamp.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Revision to stamp (default: head).",
    )

    check = sub.add_parser(
        "check",
        help="Fail if models differ from the database (alembic check).",
    )

    args = parser.parse_args(argv)

    if args.command == "current":
        return _run_alembic(["current"])
    if args.command == "history":
        return _run_alembic(["history", "--verbose"])
    if args.command == "heads":
        return _run_alembic(["heads"])
    if args.command == "upgrade":
        return _run_alembic(["upgrade", args.revision])
    if args.command == "downgrade":
        return _run_alembic(["downgrade", args.revision])
    if args.command == "stamp":
        return _run_alembic(["stamp", args.revision])
    if args.command == "check":
        return _run_alembic(["check"])
    if args.command == "revision":
        alembic_args = ["revision", "-m", args.message]
        if args.autogenerate and not args.empty:
            alembic_args.append("--autogenerate")
        return _run_alembic(alembic_args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
