"""Stable project / asset identifiers for Character & World Memory."""

from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, fallback: str = "item") -> str:
    """Convert a display name into a stable lowercase slug."""
    cleaned = " ".join(str(value).split()).casefold()
    slug = _SLUG_RE.sub("_", cleaned).strip("_")
    return slug or fallback


def project_id_for_topic(topic: str) -> str:
    """Derive a stable project id from a topic string.

    Uses a short hash so collisions across similar titles are unlikely while
    remaining filesystem-friendly and deterministic for reloads.
    """
    cleaned = " ".join(str(topic).split())
    if not cleaned:
        raise ValueError("topic must be a non-empty string")
    base = slugify(cleaned, fallback="project")[:48].rstrip("_")
    digest = hashlib.sha1(cleaned.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{base}_{digest}"
