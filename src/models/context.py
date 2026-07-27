"""Runtime context passed through pipeline stages."""

from __future__ import annotations

from src.domain.models import DomainInfo
from src.domain.prompt_context import DomainPromptContext
from src.models.base import StrictModel


class PipelineContext(StrictModel):
    """Shared run state for domain-aware pipeline stages.

    Built once after domain detection and passed through research → director →
    prompt → review → images without changing public ``generate(topic)`` APIs.
    """

    topic: str
    domain_info: DomainInfo
    prompt_context: DomainPromptContext
