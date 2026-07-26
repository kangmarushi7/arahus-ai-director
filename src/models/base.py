"""Shared Pydantic configuration for every pipeline model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base model that rejects unexpected fields and strips string whitespace.

    Forbidding extra fields makes malformed LLM output fail loudly at the
    boundary instead of silently propagating through the pipeline.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
