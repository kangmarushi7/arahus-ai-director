"""Orchestration for the topic-to-storyboard workflow."""

from __future__ import annotations

import base64
import logging
from typing import Protocol, runtime_checkable

from src.config import get_settings
from src.agents.director import DirectorAgent
from src.agents.prompt import PromptAgent
from src.agents.research import ResearchAgent
from src.agents.review import ReviewAgent
from src.models.image import ImageResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.services.llm import LLMClient
from src.services.llm_factory import create_llm


class PipelineValidationError(Exception):
    """Raised when a storyboard fails every review attempt."""

    def __init__(
        self,
        message: str,
        *,
        topic: str,
        attempts: int,
        review: ReviewResult,
    ) -> None:
        super().__init__(message)
        self.topic = topic
        self.attempts = attempts
        self.review = review


@runtime_checkable
class ImageGenerator(Protocol):
    """Renders an image prompt into an :class:`ImageResult`."""

    def generate(self, prompt: str) -> ImageResult:
        """Render one image for ``prompt``."""
        ...


@runtime_checkable
class StorageClient(Protocol):
    """Persists bytes and returns a publicly reachable URL."""

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Store ``data`` and return its public URL."""
        ...


class DirectorPipeline:
    """Runs the research, director, prompt, and image stages in order.

    By default each LLM-backed agent receives its own client from
    :func:`create_llm`, using the model names in :mod:`src.config`. Optional
    client overrides keep the pipeline testable with fakes.
    """

    def __init__(
        self,
        image_generator: ImageGenerator,
        storage_client: StorageClient,
        research_llm: LLMClient | None = None,
        director_llm: LLMClient | None = None,
        prompt_llm: LLMClient | None = None,
        review_llm: LLMClient | None = None,
        max_storyboard_retries: int | None = None,
    ) -> None:
        """Wire the pipeline's dependencies.

        Args:
            image_generator: Renders image prompts into images.
            storage_client: Persists rendered images and returns public URLs.
            research_llm: Optional override for the research agent client.
            director_llm: Optional override for the director agent client.
            prompt_llm: Optional override for the prompt agent client.
            review_llm: Optional override for the review agent client.
            max_storyboard_retries: Maximum prompt regeneration attempts after
                the initial storyboard is rejected. Defaults to pipeline config.
        """
        settings = get_settings()
        retries = (
            settings.pipeline.max_storyboard_retries
            if max_storyboard_retries is None
            else max_storyboard_retries
        )
        if retries < 0:
            raise ValueError("max_storyboard_retries cannot be negative")

        self.logger = logging.getLogger(self.__class__.__name__)
        self._image_generator = image_generator
        self._storage_client = storage_client
        self._max_storyboard_retries = retries

        self._research_llm = research_llm or create_llm(settings.llm.research_model)
        self._director_llm = director_llm or create_llm(settings.llm.director_model)
        self._prompt_llm = prompt_llm or create_llm(settings.llm.prompt_model)
        self._review_llm = review_llm or create_llm(settings.llm.review_model)

        self._research_agent = ResearchAgent(
            self._research_llm,
            debug=settings.pipeline.agent_debug,
        )
        self._director_agent = DirectorAgent(
            self._director_llm,
            debug=settings.pipeline.agent_debug,
        )
        self._prompt_agent = PromptAgent(
            self._prompt_llm,
            debug=settings.pipeline.agent_debug,
        )
        self._review_agent = ReviewAgent(
            self._review_llm,
            debug=settings.pipeline.agent_debug,
        )

    def generate(self, topic: str) -> Storyboard:
        """Build a fully rendered storyboard for ``topic``.

        The workflow is: research the topic, plan its scenes, convert those
        scenes into image prompts, review (and regenerate when rejected), then
        render and upload one image per approved scene.

        Args:
            topic: Historical subject or event.

        Returns:
            The storyboard with an uploaded image attached to every scene.

        Raises:
            ValueError: If ``topic`` is empty or contains only whitespace.
            PipelineValidationError: If the storyboard is still rejected after
                three regeneration attempts.
        """
        if not topic.strip():
            raise ValueError("topic must be a non-empty string")

        cleaned_topic = " ".join(topic.split())

        research = self._research_agent.run(cleaned_topic)
        plan = self._director_agent.run(cleaned_topic, research)
        storyboard = self._generate_approved_storyboard(plan, research)

        rendered = [self._render_scene(scene) for scene in storyboard.scenes]
        return storyboard.model_copy(update={"scenes": rendered})

    def _generate_approved_storyboard(
        self,
        plan: DirectorPlan,
        research: ResearchResult,
    ) -> Storyboard:
        """Generate and review storyboards until one passes or retries expire."""
        total_attempts = self._max_storyboard_retries + 1
        last_review: ReviewResult | None = None

        for attempt in range(1, total_attempts + 1):
            storyboard = self._prompt_agent.run(plan, research)
            review = self._review_agent.run(storyboard)
            last_review = review

            self.logger.info(
                "event=storyboard_review topic=%r attempt=%s/%s "
                "score=%s approved=%s",
                storyboard.topic,
                attempt,
                total_attempts,
                review.overall_score,
                review.approved,
            )

            if review.approved:
                return storyboard

            if attempt < total_attempts:
                self.logger.warning(
                    "event=storyboard_retry topic=%r retry=%s/%s score=%s "
                    "issues=%r recommendations=%r",
                    storyboard.topic,
                    attempt,
                    self._max_storyboard_retries,
                    review.overall_score,
                    review.issues,
                    review.recommendations,
                )

        assert last_review is not None
        self.logger.error(
            "event=storyboard_rejected topic=%r attempts=%s score=%s",
            plan.topic,
            total_attempts,
            last_review.overall_score,
        )
        raise PipelineValidationError(
            f"Storyboard for {plan.topic!r} was rejected after "
            f"{total_attempts} attempts; final score={last_review.overall_score}",
            topic=plan.topic,
            attempts=total_attempts,
            review=last_review,
        )

    def _render_scene(self, scene: Scene) -> Scene:
        """Generate and upload the image for one scene."""
        prompt = scene.image_prompt or scene.description
        image = self._image_generator.generate(prompt)

        if image.url is None and image.b64:
            url = self._storage_client.upload(
                base64.b64decode(image.b64),
                content_type="image/png",
            )
            image = image.model_copy(update={"url": url})

        return scene.model_copy(update={"image": image})
