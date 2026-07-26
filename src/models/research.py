"""Models for the research stage."""

from __future__ import annotations

from pydantic import Field

from src.models.base import StrictModel


class ResearchResult(StrictModel):
    """Factual reference material produced by the research agent."""

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
