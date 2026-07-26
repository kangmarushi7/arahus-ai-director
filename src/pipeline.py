"""Orchestration for the topic-to-storyboard workflow."""

from __future__ import annotations

import base64
import logging
import time
from typing import Protocol, runtime_checkable

from src.config import get_settings
from src.agents.director import DirectorAgent
from src.agents.prompt import PromptAgent
from src.agents.research import ResearchAgent
from src.agents.review import ReviewAgent
from src.models.image import ImageResult
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.monitoring.metrics import (
    CLOUDFLARE_UPLOAD_LATENCY,
    DIRECTOR_LATENCY,
    PIPELINE_DURATION,
    PROMPT_LATENCY,
    RESEARCH_LATENCY,
    REVIEW_LATENCY,
    RUNPOD_LATENCY,
    TOTAL_LATENCY,
    MetricsCollector,
)
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
    """Runs the research, director, prompt, review, and image stages in order.

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
        metrics: MetricsCollector | None = None,
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
            metrics: Optional metrics collector; a fresh one is created when omitted.
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
        self._metrics = metrics or MetricsCollector()

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

    def generate(self, topic: str) -> PipelineResult:
        """Build a full pipeline result for ``topic``.

        Captures research, director plan, approved storyboard, review, image
        statuses, and metrics for the studio UI.

        Args:
            topic: Historical subject or event.

        Returns:
            A :class:`PipelineResult` with every intermediate artifact.

        Raises:
            ValueError: If ``topic`` is empty or contains only whitespace.
            PipelineValidationError: If the storyboard is still rejected after
                all regeneration attempts.
        """
        if not topic.strip():
            raise ValueError("topic must be a non-empty string")

        cleaned_topic = " ".join(topic.split())
        self._metrics.reset()
        started = time.perf_counter()
        stage_timings: dict[str, float] = {
            "research_seconds": 0.0,
            "director_seconds": 0.0,
            "prompt_seconds": 0.0,
            "review_seconds": 0.0,
            "image_seconds": 0.0,
        }

        try:
            stage_started = time.perf_counter()
            with self._metrics.measure(RESEARCH_LATENCY):
                research = self._research_agent.run(cleaned_topic)
            stage_timings["research_seconds"] = time.perf_counter() - stage_started

            stage_started = time.perf_counter()
            with self._metrics.measure(DIRECTOR_LATENCY):
                plan = self._director_agent.run(cleaned_topic, research)
            stage_timings["director_seconds"] = time.perf_counter() - stage_started

            storyboard, review, prompt_seconds, review_seconds = (
                self._generate_approved_storyboard(plan, research)
            )
            stage_timings["prompt_seconds"] = prompt_seconds
            stage_timings["review_seconds"] = review_seconds

            rendered_scenes: list[Scene] = []
            images: list[GeneratedImageInfo] = []
            stage_started = time.perf_counter()
            for scene in storyboard.scenes:
                rendered, image_info = self._render_scene_safe(scene)
                rendered_scenes.append(rendered)
                images.append(image_info)
            stage_timings["image_seconds"] = time.perf_counter() - stage_started

            final_storyboard = storyboard.model_copy(update={"scenes": rendered_scenes})
        finally:
            self._metrics.record_pipeline_duration(time.perf_counter() - started)

        return PipelineResult(
            topic=cleaned_topic,
            research=research,
            plan=plan,
            storyboard=final_storyboard,
            review=review,
            images=images,
            metrics=self._studio_metrics_snapshot(stage_timings),
        )

    def _generate_approved_storyboard(
        self,
        plan: DirectorPlan,
        research: ResearchResult,
    ) -> tuple[Storyboard, ReviewResult, float, float]:
        """Generate and review storyboards until one passes or retries expire.

        Returns:
            Approved storyboard, final review, total prompt seconds, and total
            review seconds across all attempts.
        """
        total_attempts = self._max_storyboard_retries + 1
        last_review: ReviewResult | None = None
        prompt_seconds = 0.0
        review_seconds = 0.0

        for attempt in range(1, total_attempts + 1):
            stage_started = time.perf_counter()
            with self._metrics.measure(PROMPT_LATENCY):
                storyboard = self._prompt_agent.run(plan, research)
            prompt_seconds += time.perf_counter() - stage_started

            stage_started = time.perf_counter()
            with self._metrics.measure(REVIEW_LATENCY):
                review = self._review_agent.run(storyboard)
            review_seconds += time.perf_counter() - stage_started
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
                return storyboard, review, prompt_seconds, review_seconds

            if attempt < total_attempts:
                self._metrics.record_retry(1)
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

    def _render_scene_safe(self, scene: Scene) -> tuple[Scene, GeneratedImageInfo]:
        """Render one scene image without letting failures abort the pipeline."""
        prompt = scene.image_prompt or scene.description
        try:
            with self._metrics.measure(RUNPOD_LATENCY):
                image = self._image_generator.generate(prompt)

            if image.url is None and image.b64:
                with self._metrics.measure(CLOUDFLARE_UPLOAD_LATENCY):
                    url = self._storage_client.upload(
                        base64.b64decode(image.b64),
                        content_type="image/png",
                    )
                image = image.model_copy(update={"url": url})

            self._metrics.record_images_generated(1)
            info = GeneratedImageInfo(
                scene_id=scene.id,
                title=scene.title,
                prompt=prompt,
                url=image.url,
                status="ok" if image.url else "Generated (no public URL)",
            )
            return scene.model_copy(update={"image": image}), info
        except Exception as exc:  # noqa: BLE001 - keep the studio run alive
            self.logger.exception(
                "event=image_render_failed scene_id=%s title=%r",
                scene.id,
                scene.title,
            )
            info = GeneratedImageInfo(
                scene_id=scene.id,
                title=scene.title,
                prompt=prompt,
                url=None,
                status=f"Failed: {exc}",
            )
            return scene, info

    def _studio_metrics_snapshot(
        self,
        stage_timings: dict[str, float] | None = None,
    ) -> dict[str, object]:
        """Flatten metrics into the shape expected by the Streamlit dashboard."""
        snap = self._metrics.snapshot()
        latency = snap.get("latency", {})
        tokens = snap.get("tokens", {})
        timings = stage_timings or {}
        return {
            "pipeline_duration_seconds": latency.get(TOTAL_LATENCY, {}).get(
                "total_seconds",
                0.0,
            ),
            "research_seconds": round(
                timings.get(
                    "research_seconds",
                    latency.get(RESEARCH_LATENCY, {}).get("total_seconds", 0.0),
                ),
                6,
            ),
            "director_seconds": round(
                timings.get(
                    "director_seconds",
                    latency.get(DIRECTOR_LATENCY, {}).get("total_seconds", 0.0),
                ),
                6,
            ),
            "prompt_seconds": round(
                timings.get(
                    "prompt_seconds",
                    latency.get(PROMPT_LATENCY, {}).get("total_seconds", 0.0),
                ),
                6,
            ),
            "review_seconds": round(
                timings.get(
                    "review_seconds",
                    latency.get(REVIEW_LATENCY, {}).get("total_seconds", 0.0),
                ),
                6,
            ),
            "image_seconds": round(timings.get("image_seconds", 0.0), 6),
            "runpod_latency_average_seconds": latency.get(RUNPOD_LATENCY, {}).get(
                "average_seconds",
                0.0,
            ),
            "r2_upload_latency_average_seconds": latency.get(
                CLOUDFLARE_UPLOAD_LATENCY,
                {},
            ).get("average_seconds", 0.0),
            "cloudflare_upload_latency_average_seconds": latency.get(
                CLOUDFLARE_UPLOAD_LATENCY,
                {},
            ).get("average_seconds", 0.0),
            "llm_latency_average_seconds": (
                float(latency.get(RESEARCH_LATENCY, {}).get("average_seconds", 0.0))
                + float(latency.get(DIRECTOR_LATENCY, {}).get("average_seconds", 0.0))
                + float(latency.get(PROMPT_LATENCY, {}).get("average_seconds", 0.0))
                + float(latency.get(REVIEW_LATENCY, {}).get("average_seconds", 0.0))
            )
            / 4.0,
            "prompt_tokens": tokens.get("prompt_tokens", 0),
            "completion_tokens": tokens.get("completion_tokens", 0),
            "total_tokens": tokens.get("total_tokens", 0),
            "estimated_cost": snap.get("estimated_cost", 0.0),
            "images_generated": snap.get("image_count", 0),
            "image_count": snap.get("image_count", 0),
            "retry_count": snap.get("retry_count", 0),
            "raw": snap,
        }
