"""Review agent: scores a storyboard before image generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.config import get_settings
from src.models.review import ReviewResult
from src.models.storyboard import Storyboard
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

REVIEW_PROMPT_TEMPLATE = """You are a senior historical film QA reviewer.

Review the storyboard below BEFORE any images are generated. Do not rewrite \
scenes. Do not generate images. Do not modify the storyboard. Only evaluate it.

Topic: {topic}

Storyboard:
{storyboard_block}

Score each category from 0 to 100:
- historical_accuracy: period-correct people, places, clothing, architecture, weapons
- visual_quality: concreteness and cinematic clarity of scene descriptions
- scene_continuity: chronological flow and distinct non-duplicated beats
- prompt_quality: SDXL readiness of each image_prompt (architecture, lighting, \
clothing, weather, composition, materials, historical detail)

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

Use exactly this schema:

{{
  "overall_score": 0,
  "historical_accuracy": 0,
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


def generate_review_prompt(storyboard: Storyboard) -> str:
    """Build the review prompt for a storyboard.

    Args:
        storyboard: Storyboard to evaluate before image generation.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``storyboard`` is not a Storyboard instance.
    """
    if not isinstance(storyboard, Storyboard):
        raise ValueError("storyboard must be a Storyboard instance")

    payload = storyboard.model_dump(mode="json")
    return REVIEW_PROMPT_TEMPLATE.format(
        topic=storyboard.topic,
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

    def run(self, storyboard: Storyboard) -> ReviewResult:
        """Review ``storyboard`` and return a validated :class:`ReviewResult`.

        Workflow:
            1. Build a review prompt from the storyboard JSON.
            2. Call ``llm_client.generate_json(..., ReviewResult)``.
            3. Force ``approved`` from ``overall_score`` against the configured threshold.
            4. Return the review without changing the storyboard.

        Args:
            storyboard: Storyboard to evaluate before image generation.

        Returns:
            The validated review result.

        Raises:
            ValueError: If ``storyboard`` is invalid.
            ReviewAgentError: If the LLM call or validation fails.
        """
        if not isinstance(storyboard, Storyboard):
            raise ValueError("storyboard must be a Storyboard instance")

        self.logger.info(
            "event=review_start agent=ReviewAgent topic=%r scenes=%s",
            storyboard.topic,
            len(storyboard.scenes),
        )

        prompt = generate_review_prompt(storyboard)
        if self.debug:
            self.logger.debug(
                "event=review_prompt_built agent=ReviewAgent "
                "topic=%r prompt_chars=%s",
                storyboard.topic,
                len(prompt),
            )

        try:
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
            "overall_score=%s approved=%s issues=%s",
            storyboard.topic,
            finalized.overall_score,
            finalized.approved,
            len(finalized.issues),
        )
        return finalized
