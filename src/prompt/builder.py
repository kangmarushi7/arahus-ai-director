"""Merge and normalize helpers for prompt composition."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from src.prompt.models import PromptComponents, PromptContribution


_STRING_FIELDS: tuple[str, ...] = (
    "subject",
    "environment",
    "action",
    "camera",
    "lighting",
    "composition",
    "style",
    "extra_details",
)


def normalize_whitespace(text: str) -> str:
    """Collapse internal whitespace and strip ends."""
    return " ".join(text.split())


def split_csv_phrases(text: str) -> list[str]:
    """Split a comma-separated prompt bag into normalized phrases."""
    if not text or not text.strip():
        return []
    return [
        normalize_whitespace(part)
        for part in text.split(",")
        if part.strip()
    ]


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Drop empty / duplicate phrases (case-insensitive), keep first order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = normalize_whitespace(str(item))
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def merge_csv_text(*parts: str) -> str:
    """Merge comma-separated bags, dedupe, preserve first-seen order."""
    phrases: list[str] = []
    for part in parts:
        phrases.extend(split_csv_phrases(part))
    return ", ".join(dedupe_preserve_order(phrases))


def merge_string_field(base: str, overlay: str) -> str:
    """Merge two free-text fields as CSV phrases with dedupe."""
    return merge_csv_text(base, overlay)


def merge_quality_tags(*tag_lists: Sequence[str]) -> list[str]:
    """Concatenate tag lists and dedupe case-insensitively."""
    combined: list[str] = []
    for tags in tag_lists:
        combined.extend(str(tag) for tag in tags)
    return dedupe_preserve_order(combined)


def apply_contribution(
    base: PromptComponents,
    contribution: PromptContribution,
) -> PromptComponents:
    """Return ``base`` with non-empty ``contribution`` fields merged in."""
    data = base.model_dump()
    overlay = contribution.model_dump()

    for name in _STRING_FIELDS:
        incoming = overlay.get(name) or ""
        if not incoming:
            continue
        data[name] = merge_string_field(data.get(name) or "", incoming)

    incoming_tags = overlay.get("quality_tags") or []
    if incoming_tags:
        data["quality_tags"] = merge_quality_tags(
            data.get("quality_tags") or [],
            incoming_tags,
        )

    incoming_negative = overlay.get("negative_prompt") or ""
    if incoming_negative:
        data["negative_prompt"] = merge_csv_text(
            data.get("negative_prompt") or "",
            incoming_negative,
        )

    return PromptComponents.model_validate(data)


def normalize_components(components: PromptComponents) -> PromptComponents:
    """Normalize whitespace and dedupe every bag-like field on ``components``."""
    return PromptComponents(
        subject=normalize_whitespace(components.subject),
        environment=normalize_whitespace(components.environment),
        action=normalize_whitespace(components.action),
        camera=merge_csv_text(components.camera),
        lighting=merge_csv_text(components.lighting),
        composition=merge_csv_text(components.composition),
        style=merge_csv_text(components.style),
        quality_tags=merge_quality_tags(components.quality_tags),
        negative_prompt=merge_csv_text(components.negative_prompt),
        extra_details=merge_csv_text(components.extra_details),
    )


class PromptBuilder:
    """Accumulates :class:`PromptComponents` via deterministic merges.

    Used by :class:`~src.prompt.composer.PromptComposer` and available for
    callers that want to assemble components step-by-step before compose.
    """

    def __init__(self, base: PromptComponents | None = None) -> None:
        self._components = normalize_components(base or PromptComponents())
        self._metadata: dict[str, Any] = {}

    @property
    def components(self) -> PromptComponents:
        """Current merged components (copy)."""
        return self._components.model_copy(deep=True)

    @property
    def metadata(self) -> dict[str, Any]:
        """Accumulated metadata from contributions."""
        return dict(self._metadata)

    def merge(self, contribution: PromptContribution) -> PromptBuilder:
        """Apply ``contribution`` and record any metadata it carries."""
        self._components = normalize_components(
            apply_contribution(self._components, contribution)
        )
        if contribution.metadata:
            self._metadata.update(contribution.metadata)
        return self

    def merge_components(self, other: PromptComponents) -> PromptBuilder:
        """Merge a full :class:`PromptComponents` as a contribution."""
        return self.merge(
            PromptContribution(
                subject=other.subject,
                environment=other.environment,
                action=other.action,
                camera=other.camera,
                lighting=other.lighting,
                composition=other.composition,
                style=other.style,
                quality_tags=list(other.quality_tags),
                negative_prompt=other.negative_prompt,
                extra_details=other.extra_details,
            )
        )

    def build(self) -> PromptComponents:
        """Return the normalized merged components."""
        return self.components
