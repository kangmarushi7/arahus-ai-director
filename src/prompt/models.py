"""Pydantic models for the Prompt Composition Engine."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from pydantic import Field, field_validator

from src.models.base import StrictModel


def _normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


class PromptComponents(StrictModel):
    """Reusable building blocks for a structured image/video prompt.

    Callers and future packs contribute fields here; :class:`PromptComposer`
    merges and renders them. Empty strings / empty lists are ignored at render.
    """

    subject: str = ""
    environment: str = ""
    action: str = ""
    camera: str = ""
    lighting: str = ""
    composition: str = ""
    style: str = ""
    quality_tags: list[str] = Field(default_factory=list)
    negative_prompt: str = ""
    extra_details: str = ""

    @field_validator(
        "subject",
        "environment",
        "action",
        "camera",
        "lighting",
        "composition",
        "style",
        "negative_prompt",
        "extra_details",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("quality_tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [part for part in parts if part]
        if isinstance(value, (list, tuple)):
            return [
                " ".join(str(item).split())
                for item in value
                if str(item).strip()
            ]
        return value


class PromptContribution(StrictModel):
    """Partial overlay contributed by an injectable pack.

    Only non-empty fields are merged. Lists append; strings for the same slot
    are joined with ``", "`` (then deduped at compose time).
    """

    subject: str = ""
    environment: str = ""
    action: str = ""
    camera: str = ""
    lighting: str = ""
    composition: str = ""
    style: str = ""
    quality_tags: list[str] = Field(default_factory=list)
    negative_prompt: str = ""
    extra_details: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "subject",
        "environment",
        "action",
        "camera",
        "lighting",
        "composition",
        "style",
        "negative_prompt",
        "extra_details",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("quality_tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: object) -> object:
        return PromptComponents._normalize_tags(value)


class FinalPrompt(StrictModel):
    """Deterministic prompt pair ready for an image/video backend."""

    positive_prompt: str
    negative_prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("positive_prompt", "negative_prompt", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


@runtime_checkable
class PromptPack(Protocol):
    """Injectable extension that contributes prompt fragments.

    Future Knowledge Entities, Style Packs, Camera Packs, Asset Packs, and
    Character Packs implement this protocol. :class:`PromptComposer` only
    depends on this surface — pack types can be added without changing it.
    """

    @property
    def name(self) -> str:
        """Stable identifier recorded in :class:`FinalPrompt` metadata."""

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        """Return a partial overlay for ``components``.

        Args:
            components: Current merged components before this pack applies.
            context: Optional free-form context (domain id, scene id, etc.).
        """
