"""Domain classification interfaces and LLM-backed detector."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.domain.models import DomainInfo, DomainType
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

logger = logging.getLogger(__name__)

_DOMAIN_VALUES = ", ".join(member.value for member in DomainType)

DOMAIN_DETECT_PROMPT_TEMPLATE = """You are a content-domain classifier for a \
multi-domain AI film / image production system (Arahus).

Classify the topic into exactly one of these domains:
{domains}

Topic: {topic}

Rules:
1. Choose the single best-fitting domain.
2. If the topic is ambiguous or cross-domain, prefer the dominant domain; \
use "general" only when no other domain fits well.
3. confidence must be a number between 0 and 1.
4. reasoning must briefly explain the classification (1-3 sentences).
5. keywords must be concrete terms drawn from the topic (3-12 items).
6. suggested_style: production look / aesthetic for this topic and domain.
7. suggested_camera: camera, lens, framing, and movement guidance.
8. suggested_negative_prompt: comma-separated terms to avoid in image prompts.
9. Return no markdown and no explanation outside JSON.
10. Return ONLY valid JSON matching this schema:

{{
  "domain": "one of: {domains}",
  "confidence": 0.0,
  "reasoning": "...",
  "keywords": [],
  "suggested_style": "...",
  "suggested_camera": "...",
  "suggested_negative_prompt": "..."
}}
"""


class DomainDetectorError(Exception):
    """Raised when domain detection fails."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


class DomainDetector(ABC):
    """Interface for classifying a topic into a :class:`DomainType`."""

    @abstractmethod
    def detect(self, topic: str) -> DomainInfo:
        """Classify ``topic`` and return structured :class:`DomainInfo`.

        Args:
            topic: Free-form subject or brief for content generation.

        Returns:
            Validated domain classification metadata.

        Raises:
            ValueError: If ``topic`` is empty.
            DomainDetectorError: If classification cannot be completed.
        """


class LLMDomainDetector(DomainDetector):
    """LLM-backed :class:`DomainDetector` using an injected :class:`LLMClient`.

    Provider credentials and model selection stay outside this class.
    """

    def __init__(self, llm: LLMClient) -> None:
        """Wire the LLM client used for classification.

        Args:
            llm: Client that returns validated Pydantic models from prompts.
        """
        if llm is None:
            raise ValueError("llm is required")
        self._llm = llm

    def detect(self, topic: str) -> DomainInfo:
        """Classify ``topic`` via the injected LLM.

        Args:
            topic: Free-form subject or brief.

        Returns:
            Validated :class:`DomainInfo`.

        Raises:
            ValueError: If ``topic`` is empty or not a string.
            DomainDetectorError: If the LLM call or validation fails.
        """
        cleaned = _require_topic(topic)
        prompt = DOMAIN_DETECT_PROMPT_TEMPLATE.format(
            topic=cleaned,
            domains=_DOMAIN_VALUES,
        )

        try:
            result = self._llm.generate_json(prompt, DomainInfo)
        except LLMClientError as exc:
            raise DomainDetectorError(
                f"Domain detection LLM failed for topic={cleaned!r}: {exc}",
                topic=cleaned,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - keep detector boundary clean
            raise DomainDetectorError(
                f"Unexpected domain detection failure for topic={cleaned!r}: {exc}",
                topic=cleaned,
            ) from exc

        logger.info(
            "event=domain_detected topic=%r domain=%s confidence=%.3f",
            cleaned,
            result.domain.value,
            result.confidence,
        )
        return result


def _require_topic(topic: str) -> str:
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    return " ".join(topic.split())
