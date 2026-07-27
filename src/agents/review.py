"""Review agent: scores a storyboard before image generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.config import get_settings
from src.domain.models import DomainInfo, DomainType
from src.models.review import ReviewResult
from src.models.storyboard import Storyboard
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

_DEFAULT_DOMAIN_RUBRICS: dict[DomainType, str] = {
    DomainType.HISTORY: (
        "period-correct people, places, clothing, architecture, weapons, "
        "and absence of anachronisms"
    ),
    DomainType.SCIFI: (
        "coherent speculative tech, futuristic materials, and consistent "
        "world-building without breaking the established sci-fi tone"
    ),
    DomainType.FANTASY: (
        "mythic/fantastic consistency, costume and creature plausibility "
        "within the established fantasy world"
    ),
    DomainType.FINANCE: (
        "credible markets/office context, professional wardrobe, and "
        "accurate financial visual cues"
    ),
    DomainType.EDUCATION: (
        "clear instructional clarity, age-appropriate visuals, and accurate "
        "educational subject matter"
    ),
    DomainType.MARKETING: (
        "polished commercial appeal, product-readable framing, and on-brand "
        "lifestyle cues"
    ),
    DomainType.TECHNOLOGY: (
        "clean modern tech aesthetics, accurate device/UI cues, and "
        "product-keynote clarity"
    ),
    DomainType.BUSINESS: (
        "professional workplace realism, leadership/meeting context, and "
        "credible corporate visual detail"
    ),
    DomainType.GENERAL: (
        "topic fidelity, internal consistency, and absence of contradictory "
        "visual details"
    ),
}

REVIEW_PROMPT_TEMPLATE = """You are a senior film QA reviewer for {domain_label} content.

Review the storyboard below BEFORE any images are generated. Do not rewrite \
scenes. Do not generate images. Do not modify the storyboard. Only evaluate it.

Topic: {topic}
Detected domain: {domain_value} (confidence={confidence:.2f})

Domain accuracy rubric for this domain:
{domain_rubric}

Storyboard:
{storyboard_block}

Score each category from 0 to 100:
- domain_accuracy: {domain_rubric}
- visual_quality: concreteness and cinematic clarity of scene descriptions
- scene_continuity: chronological flow and distinct non-duplicated beats
- prompt_quality: FLUX readiness of each image_prompt (architecture, lighting, \
clothing, weather, composition, materials, domain-appropriate detail)

Set overall_score to a balanced summary of those category scores.

List concrete issues and actionable recommendations. Use empty lists when none.

Rules:
1. Return factual review judgments only.
2. Do not invent storyboard content that is not present.
3. Do not generate or suggest base64, URLs, or image files.
4. Do not modify titles, descriptions, or image prompts.
5. Return no markdown.
6. Return no explanation.
7. Return ONLY valid JSON.
8. Prefer the key name domain_accuracy (historical_accuracy is accepted as an alias).

Use exactly this schema:

{{
  "overall_score": 0,
  "domain_accuracy": 0,
  "visual_quality": 0,
  "scene_continuity": 0,
  "prompt_quality": 0,
  "issues": [],
  "recommendations": [],
  "approved": false
}}

Return only JSON."""


class ReviewAgentError(Exception):
    """Raised when the review agent cannot produce a :class:`ReviewResult`."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


def domain_review_rubric(domain: DomainType) -> str:
    """Return the domain-accuracy rubric text for ``domain``."""
    return _DEFAULT_DOMAIN_RUBRICS.get(domain, _DEFAULT_DOMAIN_RUBRICS[DomainType.GENERAL])


def generate_review_prompt(
    storyboard: Storyboard,
    domain_info: DomainInfo | None = None,
) -> str:
    """Build the review prompt for a storyboard.

    Args:
        storyboard: Storyboard to evaluate before image generation.
        domain_info: Optional detected domain used to specialize the rubric.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``storyboard`` is not a Storyboard instance.
    """
    if not isinstance(storyboard, Storyboard):
        raise ValueError("storyboard must be a Storyboard instance")

    domain = domain_info.domain if domain_info is not None else DomainType.GENERAL
    confidence = domain_info.confidence if domain_info is not None else 0.0
    rubric = domain_review_rubric(domain)
    payload = storyboard.model_dump(mode="json")
    return REVIEW_PROMPT_TEMPLATE.format(
        topic=storyboard.topic,
        domain_label=domain.value,
        domain_value=domain.value,
        confidence=confidence,
        domain_rubric=rubric,
        storyboard_block=json.dumps(payload, indent=2, ensure_ascii=False),
    )


def _apply_approval_policy(result: ReviewResult) -> ReviewResult:
    """Set ``approved`` from ``overall_score`` using the configured threshold."""
    threshold = get_settings().pipeline.approval_threshold
    approved = result.overall_score >= threshold
    if result.approved == approved:
        return result
    return result.model_copy(update={"approved": approved})


class ReviewAgent(BaseAgent[ReviewResult]):
    """Reviews a storyboard and returns a validated :class:`ReviewResult`.

    This agent never generates images and never mutates the storyboard. It only
    asks an injected LLM client for a structured review.
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
        storyboard: Storyboard,
        domain_info: DomainInfo | None = None,
    ) -> ReviewResult:
        """Review ``storyboard`` and return a validated :class:`ReviewResult`.

        Args:
            storyboard: Storyboard to evaluate before image generation.
            domain_info: Optional domain classification for rubric selection.

        Returns:
            The validated review result.

        Raises:
            ValueError: If ``storyboard`` is invalid.
            ReviewAgentError: If the LLM call or validation fails.
        """
        if not isinstance(storyboard, Storyboard):
            raise ValueError("storyboard must be a Storyboard instance")
        if domain_info is not None and not isinstance(domain_info, DomainInfo):
            raise ValueError("domain_info must be a DomainInfo instance when provided")

        self.logger.info(
            "event=review_start agent=ReviewAgent topic=%r scenes=%s domain=%s",
            storyboard.topic,
            len(storyboard.scenes),
            domain_info.domain.value if domain_info is not None else "general",
        )

        self._log_progress(f"Building review prompt for {storyboard.topic!r}")
        prompt = generate_review_prompt(storyboard, domain_info=domain_info)
        self._log_progress(f"Review prompt ready ({len(prompt)} chars)")
        if self.debug:
            self.logger.debug(
                "event=review_prompt_built agent=ReviewAgent "
                "topic=%r prompt_chars=%s",
                storyboard.topic,
                len(prompt),
            )

        try:
            self._log_progress("Calling review LLM…")
            result = self._execute(
                lambda: self._llm_client.generate_json(prompt, ReviewResult),
                storyboard=storyboard,
            )
        except LLMClientError as exc:
            self.logger.error(
                "event=review_failed agent=ReviewAgent topic=%r error=%s",
                storyboard.topic,
                exc,
            )
            raise ReviewAgentError(
                f"Failed to review storyboard for topic {storyboard.topic!r}: {exc}",
                topic=storyboard.topic,
            ) from exc
        except Exception as exc:
            self.logger.exception(
                "event=review_unexpected_error agent=ReviewAgent topic=%r",
                storyboard.topic,
            )
            raise ReviewAgentError(
                f"Unexpected failure reviewing topic {storyboard.topic!r}: {exc}",
                topic=storyboard.topic,
            ) from exc

        if not isinstance(result, ReviewResult):
            raise ReviewAgentError(
                "LLM client returned a non-ReviewResult value "
                f"({type(result).__name__})",
                topic=storyboard.topic,
            )

        finalized = _apply_approval_policy(result)
        self.logger.info(
            "event=review_complete agent=ReviewAgent topic=%r "
            "overall_score=%s domain_accuracy=%s approved=%s issues=%s",
            storyboard.topic,
            finalized.overall_score,
            finalized.domain_accuracy,
            finalized.approved,
            len(finalized.issues),
        )
        return finalized
