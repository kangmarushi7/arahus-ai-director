"""Research agent: turns a topic into validated reference material."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.domain.models import DomainInfo
from src.models.research import ResearchResult
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

RESEARCH_PROMPT_TEMPLATE = """You are a meticulous researcher specializing in \
concrete, verifiable detail for visual content production.

Topic: {topic}
{domain_block}
Research this topic and extract factual reference material for a film / image production.

Rules:
1. Return factual information only.
2. Do not write storytelling, narrative, or dramatic interpretation.
3. Do not include opinions, speculation, or modern commentary unless the domain \
requires contemporary terminology.
4. Prefer concrete, verifiable details: names, places, dates, objects, and materials.
5. If a detail is uncertain, omit it rather than inventing it.
6. Adapt research depth and terminology to the detected domain when provided.
7. Every array field MUST contain plain strings only (not objects).
8. Return no markdown.
9. Return no explanation.
10. Return ONLY valid JSON.

Use exactly this schema:

{{
  "topic": "{topic}",
  "time_period": "...",
  "location": "...",
  "key_people": ["..."],
  "key_locations": ["..."],
  "architecture": ["..."],
  "weapons": ["..."],
  "clothing": ["..."],
  "important_events": ["..."],
  "visual_details": ["..."],
  "historical_notes": ["..."]
}}

Return only JSON."""


class ResearchAgentError(Exception):
    """Raised when the research agent cannot produce a :class:`ResearchResult`."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


def _format_domain_block(domain_info: DomainInfo | None) -> str:
    if domain_info is None:
        return ""
    keywords = ", ".join(domain_info.keywords) if domain_info.keywords else "(none)"
    return (
        "\nDetected domain context (guide depth and terminology; do not change the "
        "JSON schema):\n"
        f"- domain: {domain_info.domain.value}\n"
        f"- confidence: {domain_info.confidence:.3f}\n"
        f"- reasoning: {domain_info.reasoning}\n"
        f"- keywords: {keywords}\n"
        f"- suggested_style: {domain_info.suggested_style or '(none)'}\n"
    )


def generate_research_prompt(
    topic: str,
    domain_info: DomainInfo | None = None,
) -> str:
    """Build the research prompt for a topic.

    Args:
        topic: Subject or event to research.
        domain_info: Optional domain classification guiding tone/terminology.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``topic`` is empty or contains only whitespace.
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    return RESEARCH_PROMPT_TEMPLATE.format(
        topic=" ".join(topic.split()),
        domain_block=_format_domain_block(domain_info),
    )


class ResearchAgent(BaseAgent[ResearchResult]):
    """Produces a validated :class:`ResearchResult` for a topic.

    Depends only on an injected :class:`~src.services.llm.LLMClient`. Provider
    details (API keys, base URLs, model names) stay outside this class.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        debug: bool | None = None,
    ) -> None:
        """Store the injected LLM client.

        Args:
            llm_client: Client used to request validated JSON.
            max_retries: Forwarded to :class:`BaseAgent`.
            retry_backoff_seconds: Forwarded to :class:`BaseAgent`.
            debug: Forwarded to :class:`BaseAgent`.
        """
        super().__init__(
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            debug=debug,
        )
        self._llm_client = llm_client

    def run(
        self,
        topic: str,
        domain_info: DomainInfo | None = None,
    ) -> ResearchResult:
        """Research ``topic`` and return a validated :class:`ResearchResult`.

        Workflow:
            1. Build the research prompt (optionally domain-aware).
            2. Call ``llm_client.generate_json(...)``.
            3. Receive a Pydantic-validated ``ResearchResult``.
            4. Return that model (schema unchanged).

        Args:
            topic: Subject or event.
            domain_info: Optional domain classification for research guidance.

        Returns:
            The validated research result.

        Raises:
            ValueError: If ``topic`` is empty or not a string.
            ResearchAgentError: If the LLM request, JSON parse, or validation fails.
        """
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        if domain_info is not None and not isinstance(domain_info, DomainInfo):
            raise ValueError("domain_info must be a DomainInfo instance when provided")

        cleaned_topic = " ".join(topic.split())
        self._log_progress(f"Building research prompt for {cleaned_topic!r}")
        self.logger.info(
            "event=research_start agent=ResearchAgent topic=%r domain=%s",
            cleaned_topic,
            domain_info.domain.value if domain_info else None,
        )

        prompt = generate_research_prompt(cleaned_topic, domain_info)
        self._log_progress(f"Research prompt ready ({len(prompt)} chars)")
        if self.debug:
            self.logger.debug(
                "event=research_prompt_built agent=ResearchAgent "
                "topic=%r prompt_chars=%s",
                cleaned_topic,
                len(prompt),
            )

        try:
            self._log_progress("Calling research LLM…")
            result = self._execute(
                lambda: self._llm_client.generate_json(prompt, ResearchResult),
                topic=cleaned_topic,
                domain_info=domain_info,
            )
        except LLMClientError as exc:
            # Surface missing-topic / empty-payload as a clear agent error;
            # shape mismatches are handled by ResearchResult normalization.
            self.logger.error(
                "event=research_failed agent=ResearchAgent topic=%r error=%s",
                cleaned_topic,
                exc,
            )
            raise ResearchAgentError(
                f"Failed to research topic {cleaned_topic!r}: {exc}",
                topic=cleaned_topic,
            ) from exc
        except Exception as exc:
            self.logger.exception(
                "event=research_unexpected_error agent=ResearchAgent topic=%r",
                cleaned_topic,
            )
            raise ResearchAgentError(
                f"Unexpected failure researching topic {cleaned_topic!r}: {exc}",
                topic=cleaned_topic,
            ) from exc

        if not isinstance(result, ResearchResult):
            raise ResearchAgentError(
                "LLM client returned a non-ResearchResult value "
                f"({type(result).__name__})",
                topic=cleaned_topic,
            )

        self.logger.info(
            "event=research_complete agent=ResearchAgent topic=%r "
            "time_period=%r location=%r key_people=%s",
            result.topic,
            result.time_period,
            result.location,
            len(result.key_people),
        )
        return result
