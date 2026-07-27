"""Models for the research stage."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from src.models.base import StrictModel
from src.models.research_normalize import normalize_research_payload


class ResearchResult(StrictModel):
    """Factual reference material produced by the research agent.

    Only ``topic`` is required. All other fields default to empty values so
    heterogeneous LLM JSON can be normalized before validation.
    """

    topic: str
    time_period: str = ""
    location: str = ""
    key_people: list[str] = Field(default_factory=list)
    key_locations: list[str] = Field(default_factory=list)
    architecture: list[str] = Field(default_factory=list)
    weapons: list[str] = Field(default_factory=list)
    clothing: list[str] = Field(default_factory=list)
    important_events: list[str] = Field(default_factory=list)
    visual_details: list[str] = Field(default_factory=list)
    historical_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, data: Any) -> Any:
        """Normalize model-specific JSON shapes before field validation."""
        if isinstance(data, cls):
            return data
        return normalize_research_payload(data)
