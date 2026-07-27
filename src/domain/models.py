"""Pydantic models and enums for the Domain Intelligence module."""

from __future__ import annotations

import enum

from pydantic import Field

from src.models.base import StrictModel


class DomainType(str, enum.Enum):
    """Supported content domains for Arahus generation pipelines."""

    HISTORY = "history"
    SCIFI = "scifi"
    FINANCE = "finance"
    EDUCATION = "education"
    MARKETING = "marketing"
    FANTASY = "fantasy"
    TECHNOLOGY = "technology"
    BUSINESS = "business"
    GENERAL = "general"


class DomainInfo(StrictModel):
    """Classification result produced by a :class:`~src.domain.detector.DomainDetector`.

    Attributes:
        domain: Detected content domain.
        confidence: Classifier confidence in ``[0, 1]``.
        reasoning: Short explanation of why this domain was chosen.
        keywords: Topic keywords that influenced the decision.
        suggested_style: Visual / tonal style hint for prompt builders.
        suggested_camera: Camera / framing hint for image prompts.
        suggested_negative_prompt: Terms to discourage in image generation.
    """

    domain: DomainType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    keywords: list[str] = Field(default_factory=list)
    suggested_style: str = ""
    suggested_camera: str = ""
    suggested_negative_prompt: str = ""


class DomainConfig(StrictModel):
    """Static configuration registered for a :class:`DomainType`.

    Registry entries drive style defaults independent of any single detection
    call. Plugins may register additional configs at runtime.
    """

    domain: DomainType
    label: str
    description: str = ""
    default_keywords: list[str] = Field(default_factory=list)
    suggested_style: str = ""
    suggested_camera: str = ""
    suggested_negative_prompt: str = ""


class DomainResolution(StrictModel):
    """Combined detection + registry payload for pipeline consumers."""

    info: DomainInfo
    config: DomainConfig
