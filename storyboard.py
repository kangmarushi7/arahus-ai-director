"""Generate a four-scene cinematic storyboard from a historical topic."""

from __future__ import annotations

import json
from typing import Any

# Four narrative beats that map cleanly onto a short visual sequence.
SCENE_BEATS: tuple[dict[str, str], ...] = (
    {
        "id": "1",
        "beat": "establish",
        "title": "Establishing Moment",
        "focus": (
            "wide establishing shot introducing the era, place, and atmosphere "
            "before the central conflict begins"
        ),
    },
    {
        "id": "2",
        "beat": "rising",
        "title": "Rising Tension",
        "focus": (
            "medium cinematic shot showing key figures gathering momentum, "
            "with visible stakes and historical detail"
        ),
    },
    {
        "id": "3",
        "beat": "climax",
        "title": "Climactic Turning Point",
        "focus": (
            "dramatic climax capturing the decisive action, emotion, and "
            "peak energy of the event"
        ),
    },
    {
        "id": "4",
        "beat": "aftermath",
        "title": "Aftermath",
        "focus": (
            "quiet aftermath or consequence shot that leaves a lasting "
            "emotional and historical impression"
        ),
    },
)

# Shared visual language optimized for text-to-image models.
CINEMATIC_SUFFIX = (
    "cinematic historical drama, period-accurate costumes and architecture, "
    "dramatic lighting, film still, ultra detailed, 35mm photography"
)


def _build_scene_prompt(topic: str, focus: str) -> str:
    """Compose one image-ready prompt for a storyboard beat."""
    cleaned = " ".join(topic.split())
    return f"{cleaned}, {focus}, {CINEMATIC_SUFFIX}"


def generate_storyboard(topic: str) -> dict[str, Any]:
    """Build a four-scene storyboard for a historical topic.

    Args:
        topic: Historical subject or event, e.g. "Fall of Constantinople 1453".

    Returns:
        Structured storyboard as a JSON-serializable dictionary:

        {
          "topic": "...",
          "scene_count": 4,
          "scenes": [
            {
              "id": "1",
              "beat": "establish",
              "title": "Establishing Moment",
              "prompt": "..."
            },
            ...
          ]
        }
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    cleaned_topic = " ".join(topic.split())
    scenes = [
        {
            "id": beat["id"],
            "beat": beat["beat"],
            "title": beat["title"],
            "prompt": _build_scene_prompt(cleaned_topic, beat["focus"]),
        }
        for beat in SCENE_BEATS
    ]

    return {
        "topic": cleaned_topic,
        "scene_count": len(scenes),
        "scenes": scenes,
    }


def generate_storyboard_json(topic: str, *, indent: int | None = 2) -> str:
    """Return the storyboard as a formatted JSON string."""
    return json.dumps(generate_storyboard(topic), indent=indent, ensure_ascii=False)


if __name__ == "__main__":
    sample = generate_storyboard_json("Fall of Constantinople 1453")
    print(sample)
