"""Character consistency helpers for visual identity across scenes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.database.session import get_session
from src.models.research import ResearchResult
from src.repositories.character_repository import CharacterRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    """In-memory character appearance used during a pipeline run."""

    name: str
    appearance: str = ""
    role: str = ""


def profiles_from_research(research: ResearchResult) -> list[CharacterProfile]:
    """Build character profiles from research ``key_people``."""
    profiles: list[CharacterProfile] = []
    seen: set[str] = set()
    for raw in research.key_people:
        name = " ".join(str(raw).split())
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        appearance = (
            f"consistent likeness of {name}, matching period wardrobe and "
            f"identity across all scenes"
        )
        if research.time_period:
            appearance += f", era {research.time_period}"
        profiles.append(
            CharacterProfile(name=name, appearance=appearance, role="key_person")
        )
    return profiles


def format_character_bible(profiles: list[CharacterProfile]) -> str:
    """Render a compact character bible for agent prompts."""
    if not profiles:
        return ""
    lines = ["Character bible (keep visual identity consistent across scenes):"]
    for profile in profiles:
        lines.append(f"- {profile.name}: {profile.appearance}")
    return "\n".join(lines)


def persist_character_profiles(profiles: list[CharacterProfile]) -> dict[str, str]:
    """Upsert characters into the DB when configured; return name→id map.

    Returns an empty dict when the database is unavailable.
    """
    if not profiles:
        return {}
    try:
        with get_session() as session:
            repo = CharacterRepository(session)
            mapping: dict[str, str] = {}
            for profile in profiles:
                existing = repo.find_by_name(profile.name)
                if existing is None:
                    existing = repo.find_by_alias(profile.name)
                if existing is None:
                    row = repo.create(
                        name=profile.name,
                        appearance=profile.appearance,
                        role=profile.role or None,
                    )
                else:
                    row = repo.update(
                        existing,
                        appearance=profile.appearance or existing.appearance,
                        role=profile.role or existing.role,
                    )
                mapping[profile.name] = str(row.id)
            logger.info(
                "event=characters_persisted count=%s names=%r",
                len(mapping),
                list(mapping),
            )
            return mapping
    except Exception as exc:  # noqa: BLE001 - optional persistence
        logger.warning("event=characters_persist_skipped error=%s", exc)
        return {}


def names_mentioned_in_text(text: str, names: list[str]) -> list[str]:
    """Return character names that appear in ``text`` (case-insensitive)."""
    hay = text.casefold()
    found: list[str] = []
    for name in names:
        pattern = re.compile(rf"\b{re.escape(name.casefold())}\b")
        if pattern.search(hay):
            found.append(name)
    return found
