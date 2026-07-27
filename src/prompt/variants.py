"""Prompt variant models and style profiles for optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import Field, field_validator

from src.models.base import StrictModel


def _normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


class PromptVariant(StrictModel):
    """One scored prompt candidate produced by :class:`PromptOptimizer`."""

    id: str
    style_name: str
    positive_prompt: str
    negative_prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "style_name", "positive_prompt", "negative_prompt", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


@dataclass(frozen=True, slots=True)
class VariantStyleProfile:
    """Deterministic wording / camera / lighting / composition deltas.

    Profiles change presentation language while preserving scene meaning
    (subject, environment, and action stay semantically the same).
    """

    style_name: str
    subject_framing: str
    action_framing: str
    style_overlay: str
    camera_overlay: str
    lighting_overlay: str
    composition_overlay: str
    quality_tags: tuple[str, ...]
    negative_overlay: str = ""


# Fixed order used by the optimizer (Cinematic → Documentary → Dramatic).
VARIANT_STYLE_PROFILES: tuple[VariantStyleProfile, ...] = (
    VariantStyleProfile(
        style_name="Cinematic",
        subject_framing="cinematic portrayal of {subject}",
        action_framing="{action}, staged with filmic tension",
        style_overlay=(
            "cinematic color grade, anamorphic bokeh, filmic contrast, "
            "theatrical atmosphere"
        ),
        camera_overlay=(
            "wide anamorphic framing, slow dolly-in, shallow depth of field, "
            "motivated camera move"
        ),
        lighting_overlay=(
            "dramatic cinematic key light, volumetric haze, rich contrast, "
            "rim accents"
        ),
        composition_overlay=(
            "rule of thirds, layered depth, strong leading lines, heroic scale"
        ),
        quality_tags=("cinematic still", "film grain", "high detail"),
        negative_overlay="flat lighting, snapshot look, amateur framing",
    ),
    VariantStyleProfile(
        style_name="Documentary",
        subject_framing="observational documentary view of {subject}",
        action_framing="{action}, captured as it unfolds",
        style_overlay=(
            "documentary realism, natural color, restrained grade, "
            "truthful atmosphere"
        ),
        camera_overlay=(
            "eye-level 35mm observational framing, stable coverage, "
            "subtle handheld authenticity"
        ),
        lighting_overlay=(
            "available light, soft natural fill, gentle contrast, "
            "motivated practicals"
        ),
        composition_overlay=(
            "clear subject hierarchy, environmental context, balanced negative space"
        ),
        quality_tags=("documentary still", "natural detail", "sharp focus"),
        negative_overlay="over-stylized CGI, exaggerated drama, heavy color grade",
    ),
    VariantStyleProfile(
        style_name="Dramatic",
        subject_framing="intensely dramatic depiction of {subject}",
        action_framing="{action}, heightened emotional peak",
        style_overlay=(
            "high-drama visual language, bold contrast, charged atmosphere, "
            "expressive color"
        ),
        camera_overlay=(
            "low-angle hero framing, tight medium close-up energy, "
            "dynamic push-in"
        ),
        lighting_overlay=(
            "hard dramatic side light, deep shadows, stark highlights, "
            "chiaroscuro mood"
        ),
        composition_overlay=(
            "centered power framing, compressed depth, confrontational silhouette"
        ),
        quality_tags=("dramatic still", "high contrast", "intense detail"),
        negative_overlay="flat documentary look, washed out lighting, weak contrast",
    ),
)


def new_variant_id(style_name: str) -> str:
    """Return a stable-looking unique id for a variant."""
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in style_name)
    slug = "-".join(part for part in slug.split("-") if part)
    return f"{slug}-{uuid4().hex[:10]}"


def frame_subject(profile: VariantStyleProfile, subject: str) -> str:
    """Apply style-specific wording around ``subject`` without changing identity."""
    cleaned = " ".join(subject.split())
    if not cleaned:
        return ""
    return profile.subject_framing.format(subject=cleaned)


def frame_action(profile: VariantStyleProfile, action: str) -> str:
    """Apply style-specific wording around ``action`` when present."""
    cleaned = " ".join(action.split())
    if not cleaned:
        return ""
    return profile.action_framing.format(action=cleaned)
