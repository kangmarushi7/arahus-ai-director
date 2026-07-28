"""Shared path sanitization for artifact stores."""

from __future__ import annotations


def safe_path_segment(value: str, *, fallback: str = "unknown") -> str:
    """Return a filesystem-safe single path segment (no traversal).

    Strips whitespace, collapses internal spaces, and replaces ``..``, ``/``,
    and ``\\``. Empty results become ``fallback``.
    """
    cleaned = " ".join(str(value or "").split())
    safe = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_")
    safe = "".join(ch for ch in safe if ch.isprintable())
    return safe or fallback
