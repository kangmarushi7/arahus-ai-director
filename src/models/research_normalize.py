"""Normalize heterogeneous LLM research JSON before Pydantic validation.

Models (Gemini, Claude, DeepSeek, Qwen, etc.) often return list items as
objects or mix scalars into arrays. This layer coerces those shapes into the
canonical :class:`~src.models.research.ResearchResult` schema so the pipeline
only fails when required semantic content is actually missing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

# Human-readable object keys, highest priority first.
_OBJECT_TEXT_KEYS: tuple[str, ...] = (
    "name",
    "title",
    "value",
    "label",
    "text",
    "description",
)

_STRING_FIELDS: tuple[str, ...] = (
    "topic",
    "time_period",
    "location",
)
_LIST_FIELDS: tuple[str, ...] = (
    "key_people",
    "key_locations",
    "architecture",
    "weapons",
    "clothing",
    "important_events",
    "visual_details",
    "historical_notes",
)
_KNOWN_FIELDS: frozenset[str] = frozenset(_STRING_FIELDS + _LIST_FIELDS)


def normalize_research_payload(data: object) -> dict[str, Any]:
    """Coerce raw LLM JSON into a ResearchResult-compatible mapping.

    Args:
        data: Parsed JSON value (typically a ``dict``).

    Returns:
        A dict with known fields coerced to ``str`` / ``list[str]``.

    Raises:
        ValueError: If ``data`` is not a mapping or ``topic`` is missing/empty
            after coercion (the only required semantic field).
    """
    if not isinstance(data, Mapping):
        raise ValueError(
            f"Research JSON must be an object, got {type(data).__name__}"
        )

    raw = dict(data)
    for key in [k for k in raw if k not in _KNOWN_FIELDS]:
        logger.debug(
            "event=research_coerce action=drop_unknown field=%s value_type=%s",
            key,
            type(raw[key]).__name__,
        )
        raw.pop(key, None)

    out: dict[str, Any] = {}

    for field in _STRING_FIELDS:
        if field not in raw or raw[field] is None:
            if field == "topic":
                continue
            out[field] = ""
            if field not in raw:
                logger.debug(
                    "event=research_coerce action=default_missing field=%s value=''",
                    field,
                )
            continue
        out[field] = _coerce_scalar_string(raw[field], field=field)

    for field in _LIST_FIELDS:
        if field not in raw or raw[field] is None:
            out[field] = []
            if field not in raw:
                logger.debug(
                    "event=research_coerce action=default_missing field=%s value=[]",
                    field,
                )
            continue
        out[field] = _coerce_string_list(raw[field], field=field)

    topic = out.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Research JSON missing required field 'topic'")

    out["topic"] = " ".join(topic.split())
    return out


def _coerce_scalar_string(value: object, *, field: str) -> str:
    """Coerce a scalar field to a stripped string."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, bool):
        text = "true" if value else "false"
        logger.debug(
            "event=research_coerce action=bool_to_str field=%s value=%r",
            field,
            text,
        )
        return text

    if isinstance(value, (int, float)):
        text = _format_number(value)
        logger.debug(
            "event=research_coerce action=number_to_str field=%s value=%r",
            field,
            text,
        )
        return text

    if isinstance(value, Mapping):
        text = _object_to_text(value)
        logger.debug(
            "event=research_coerce action=object_to_str field=%s value=%r",
            field,
            text[:200],
        )
        return text

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [
            item
            for item in (_coerce_list_item(v, field=field) for v in value)
            if item
        ]
        text = "; ".join(parts)
        logger.debug(
            "event=research_coerce action=list_to_str field=%s items=%s",
            field,
            len(parts),
        )
        return text

    text = str(value).strip()
    logger.debug(
        "event=research_coerce action=str_fallback field=%s value_type=%s",
        field,
        type(value).__name__,
    )
    return text


def _coerce_string_list(value: object, *, field: str) -> list[str]:
    """Coerce a list field into ``list[str]``."""
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            logger.debug(
                "event=research_coerce action=empty_str_to_list field=%s",
                field,
            )
            return []
        logger.debug(
            "event=research_coerce action=str_to_singleton_list field=%s",
            field,
        )
        return [cleaned]

    if isinstance(value, Mapping):
        item = _coerce_list_item(value, field=field)
        logger.debug(
            "event=research_coerce action=object_to_singleton_list field=%s",
            field,
        )
        return [item] if item else []

    if isinstance(value, (bool, int, float)):
        item = _coerce_list_item(value, field=field)
        logger.debug(
            "event=research_coerce action=scalar_to_singleton_list field=%s",
            field,
        )
        return [item] if item else []

    if not isinstance(value, Sequence):
        item = _coerce_list_item(value, field=field)
        logger.debug(
            "event=research_coerce action=unknown_to_list field=%s value_type=%s",
            field,
            type(value).__name__,
        )
        return [item] if item else []

    result: list[str] = []
    for index, entry in enumerate(value):
        item = _coerce_list_item(entry, field=field, index=index)
        if item:
            result.append(item)
    return result


def _coerce_list_item(
    value: object,
    *,
    field: str,
    index: int | None = None,
) -> str | None:
    """Coerce one list entry to a human-readable string, or ``None`` to skip."""
    if value is None:
        logger.debug(
            "event=research_coerce action=skip_null field=%s index=%s",
            field,
            index,
        )
        return None

    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None

    if isinstance(value, bool):
        text = "true" if value else "false"
        logger.debug(
            "event=research_coerce action=bool_item field=%s index=%s value=%r",
            field,
            index,
            text,
        )
        return text

    if isinstance(value, (int, float)):
        text = _format_number(value)
        logger.debug(
            "event=research_coerce action=number_item field=%s index=%s value=%r",
            field,
            index,
            text,
        )
        return text

    if isinstance(value, Mapping):
        text = _object_to_text(value)
        logger.debug(
            "event=research_coerce action=object_item field=%s index=%s "
            "keys=%s value=%r",
            field,
            index,
            list(value.keys()),
            text[:200],
        )
        return text or None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [
            part
            for part in (_coerce_list_item(v, field=field) for v in value)
            if part
        ]
        text = "; ".join(parts)
        logger.debug(
            "event=research_coerce action=nested_list_item field=%s index=%s",
            field,
            index,
        )
        return text or None

    text = str(value).strip()
    logger.debug(
        "event=research_coerce action=str_fallback_item field=%s index=%s "
        "value_type=%s",
        field,
        index,
        type(value).__name__,
    )
    return text or None


def _object_to_text(obj: Mapping[str, Any]) -> str:
    """Extract the best human-readable string from an object-shaped item."""
    for key in _OBJECT_TEXT_KEYS:
        if key not in obj or obj[key] is None:
            continue
        candidate = obj[key]
        text = _scalar_to_text(candidate)
        if text:
            return text

    # No priority key — join remaining scalar values (Gemini-style shapes).
    parts: list[str] = []
    for candidate in obj.values():
        text = _scalar_to_text(candidate)
        if text:
            parts.append(text)
    if parts:
        return " - ".join(parts)

    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(obj)


def _scalar_to_text(value: object) -> str | None:
    """Return a cleaned string for a scalar, or ``None`` if not usable."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    return None


def _format_number(value: int | float) -> str:
    """Format numbers without unnecessary trailing zeros."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
