"""Orchestration for the topic-to-storyboard workflow."""

from __future__ import annotations

import base64
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.progress import ProgressCallback, ProgressReporter
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
        self._reporter: ProgressReporter | None = None

    def generate(
        self,
        topic: str,
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineResult:
        """Build a full pipeline result for ``topic``.

        Captures research, director plan, approved storyboard, review, image
        statuses, and metrics for the studio UI.

        Args:
            topic: Historical subject or event.
            progress_callback: Optional callable invoked with human-readable
                progress lines for live consoles.

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
        self._reporter = ProgressReporter(callback=progress_callback)
        self._bind_step_loggers()
        self._emit(f"Pipeline started for topic: {cleaned_topic}", progress=0.01)
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
            self._begin_stage("Research")
            self._emit(
                "Stage 1/5 — Research Agent: gathering historical facts…",
                progress=0.05,
            )
            stage_started = time.perf_counter()
            with self._metrics.measure(RESEARCH_LATENCY):
                research = self._research_agent.run(cleaned_topic)
            stage_timings["research_seconds"] = time.perf_counter() - stage_started
            self._complete_stage("Research")
            self._emit(
                "Research complete "
                f"({stage_timings['research_seconds']:.1f}s) — "
                f"location={research.location or 'n/a'}, "
                f"people={len(research.key_people)}, "
                f"events={len(getattr(research, 'important_events', []) or [])}",
                progress=0.22,
            )

            self._begin_stage("Director")
            self._emit(
                "Stage 2/5 — Director Agent: planning four scenes…",
                progress=0.25,
            )
            stage_started = time.perf_counter()
            with self._metrics.measure(DIRECTOR_LATENCY):
                plan = self._director_agent.run(cleaned_topic, research)
            stage_timings["director_seconds"] = time.perf_counter() - stage_started
            self._complete_stage("Director")
            self._emit(
                "Director complete "
                f"({stage_timings['director_seconds']:.1f}s) — "
                f"{len(plan.scenes)} scenes",
                progress=0.42,
            )
            for scene in plan.scenes:
                self._emit(f"  Scene {scene.id}: {scene.title}")

            self._emit(
                "Stage 3–4/5 — Prompt + Review Agents…",
                progress=0.45,
            )
            storyboard, review, prompt_seconds, review_seconds = (
                self._generate_approved_storyboard(plan, research)
            )
            stage_timings["prompt_seconds"] = prompt_seconds
            stage_timings["review_seconds"] = review_seconds
            self._emit(
                "Storyboard approved "
                f"(score={review.overall_score:.0f}, "
                f"prompt={prompt_seconds:.1f}s, review={review_seconds:.1f}s)",
                progress=0.72,
            )

            self._begin_stage("Images")
            self._emit("Stage 5/5 — Image generation…", progress=0.75)
            stage_started = time.perf_counter()
            final_storyboard, images = self._render_storyboard_images(storyboard)
            stage_timings["image_seconds"] = time.perf_counter() - stage_started
            self._complete_stage("Images")
            self._emit(
                f"Image stage complete ({stage_timings['image_seconds']:.1f}s) — "
                f"{sum(1 for item in images if item.url)}/"
                f"{len(images)} scenes with URLs",
                progress=0.98,
            )

            total = time.perf_counter() - started
            self._emit(f"Pipeline finished in {total:.1f}s", progress=1.0)
        finally:
            self._metrics.record_pipeline_duration(time.perf_counter() - started)
            self._unbind_step_loggers()
            self._reporter = None

        return PipelineResult(
            topic=cleaned_topic,
            research=research,
            plan=plan,
            storyboard=final_storyboard,
            review=review,
            images=images,
            metrics=self._studio_metrics_snapshot(stage_timings),
        )

    def _bind_step_loggers(self) -> None:
        """Attach fine-grained step logging to agents and LLM clients."""

        def step(message: str) -> None:
            self._emit(f"  · {message}")

        for agent in (
            self._research_agent,
            self._director_agent,
            self._prompt_agent,
            self._review_agent,
        ):
            agent.progress_callback = step
        for llm in (
            self._research_llm,
            self._director_llm,
            self._prompt_llm,
            self._review_llm,
        ):
            llm.progress_callback = step

    def _unbind_step_loggers(self) -> None:
        """Clear progress sinks after a pipeline run."""
        for agent in (
            self._research_agent,
            self._director_agent,
            self._prompt_agent,
            self._review_agent,
        ):
            agent.progress_callback = None
        for llm in (
            self._research_llm,
            self._director_llm,
            self._prompt_llm,
            self._review_llm,
        ):
            llm.progress_callback = None

    def _emit(self, message: str, *, progress: float | None = None) -> None:
        """Send a progress line to the optional reporter and logger."""
        self.logger.info("%s", message)
        reporter = self._reporter
        if reporter is not None:
            reporter.emit(message, progress=progress)

    def _begin_stage(self, name: str) -> None:
        reporter = self._reporter
        if reporter is not None:
            reporter.begin_stage(name)

    def _set_stage(self, name: str, fraction: float) -> None:
        reporter = self._reporter
        if reporter is not None:
            reporter.set_stage(name, fraction)

    def _complete_stage(self, name: str) -> None:
        reporter = self._reporter
        if reporter is not None:
            reporter.complete_stage(name)

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
            # Prompt/review share 0.45 → 0.72 of the bar across attempts.
            attempt_span = 0.27 / total_attempts
            attempt_base = 0.45 + (attempt - 1) * attempt_span

            self._begin_stage("Prompt")
            self._set_stage("Prompt", 0.15)
            self._emit(
                f"Prompt Agent attempt {attempt}/{total_attempts}: "
                "writing SDXL image prompts…",
                progress=attempt_base,
            )
            stage_started = time.perf_counter()
            with self._metrics.measure(PROMPT_LATENCY):
                storyboard = self._prompt_agent.run(plan, research)
            prompt_seconds += time.perf_counter() - stage_started
            self._complete_stage("Prompt")
            self._emit(
                f"Prompt Agent finished attempt {attempt} "
                f"({time.perf_counter() - stage_started:.1f}s) — "
                f"{len(storyboard.scenes)} prompts",
                progress=attempt_base + attempt_span * 0.45,
            )

            self._begin_stage("Review")
            self._set_stage("Review", 0.15)
            self._emit(
                f"Review Agent attempt {attempt}/{total_attempts}: "
                "scoring storyboard…",
                progress=attempt_base + attempt_span * 0.55,
            )
            stage_started = time.perf_counter()
            with self._metrics.measure(REVIEW_LATENCY):
                review = self._review_agent.run(storyboard)
            review_seconds += time.perf_counter() - stage_started
            last_review = review
            self._complete_stage("Review")

            self.logger.info(
                "event=storyboard_review topic=%r attempt=%s/%s "
                "score=%s approved=%s",
                storyboard.topic,
                attempt,
                total_attempts,
                review.overall_score,
                review.approved,
            )
            self._emit(
                f"Review score={review.overall_score:.0f} "
                f"history={review.historical_accuracy:.0f} "
                f"visual={review.visual_quality:.0f} "
                f"continuity={review.scene_continuity:.0f} "
                f"prompts={review.prompt_quality:.0f} "
                f"approved={review.approved}",
                progress=attempt_base + attempt_span,
            )
            if review.issues:
                self._emit(f"  Issues: {'; '.join(review.issues[:3])}")

            if review.approved:
                return storyboard, review, prompt_seconds, review_seconds

            if attempt < total_attempts:
                self._metrics.record_retry(1)
                self._emit(
                    "Storyboard rejected — regenerating prompts "
                    f"(retry {attempt}/{self._max_storyboard_retries})"
                )
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
        self._emit(
            f"Storyboard rejected after {total_attempts} attempts "
            f"(final score={last_review.overall_score:.0f})"
        )
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

    def _render_storyboard_images(
        self,
        storyboard: Storyboard,
    ) -> tuple[Storyboard, list[GeneratedImageInfo]]:
        """Render every storyboard scene concurrently, preserving order.

        Uses :class:`~concurrent.futures.ThreadPoolExecutor` so RunPod/R2 I/O
        overlaps across scenes. A failure on one scene does not cancel the
        others; errors are attached to the corresponding :class:`Scene`.

        Args:
            storyboard: Approved storyboard with image prompts.

        Returns:
            A complete storyboard (scenes in original order, each with
            ``image`` and/or ``error``) plus studio image-info rows.
        """
        scenes = list(storyboard.scenes)
        scene_count = len(scenes)
        if scene_count == 0:
            return storyboard, []

        self._emit(
            f"Rendering {scene_count} scenes concurrently "
            f"(max_workers={scene_count})…"
        )
        for index, scene in enumerate(scenes):
            image_number = index + 1
            self._set_stage("Images", image_number / (scene_count * 2))
            self._emit(
                f"Generating image {image_number}/{scene_count}...",
                progress=0.75 + (0.05 * (index / scene_count)),
            )
            self._emit(
                f"  Queued scene {scene.id}: {scene.title} "
                f"({len(scene.image_prompt or '')} chars)"
            )

        # Preserve input order: index → (Scene, GeneratedImageInfo).
        ordered: list[tuple[Scene, GeneratedImageInfo] | None] = [None] * scene_count
        completed = 0

        with ThreadPoolExecutor(max_workers=scene_count) as executor:
            future_to_index = {
                executor.submit(self._render_scene_safe, scene): index
                for index, scene in enumerate(scenes)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                source = scenes[index]
                try:
                    rendered, info = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate worker crashes
                    self.logger.exception(
                        "event=image_render_worker_crashed scene_id=%s title=%r",
                        source.id,
                        source.title,
                    )
                    error_message = f"{type(exc).__name__}: {exc}"
                    rendered = source.model_copy(
                        update={"image": None, "error": error_message}
                    )
                    info = GeneratedImageInfo(
                        scene_id=source.id,
                        title=source.title,
                        prompt=source.image_prompt or source.description,
                        url=None,
                        status=f"Failed: {error_message}",
                    )

                ordered[index] = (rendered, info)
                completed += 1
                image_number = index + 1
                self._set_stage("Images", 0.5 + (0.5 * (completed / scene_count)))
                progress = 0.80 + (0.18 * (completed / scene_count))
                self._emit(
                    f"Completed image {image_number}/{scene_count}... "
                    f"({info.status}"
                    + (f" → {info.url}" if info.url else "")
                    + ")",
                    progress=progress,
                )

        rendered_scenes = [item[0] for item in ordered if item is not None]
        images = [item[1] for item in ordered if item is not None]
        # Defensive: keep length/order identical to the input storyboard.
        if len(rendered_scenes) != scene_count:
            raise RuntimeError(
                "Concurrent image stage lost scenes: "
                f"expected {scene_count}, got {len(rendered_scenes)}"
            )

        return (
            storyboard.model_copy(update={"scenes": rendered_scenes}),
            images,
        )

    def _render_scene_safe(self, scene: Scene) -> tuple[Scene, GeneratedImageInfo]:
        """Render one scene image without letting failures abort the pool.

        Logs wall-clock latency for the scene on both success and failure.
        Successful renders attach an :class:`ImageResult`; failures attach an
        ``error`` string on the :class:`Scene` and leave ``image`` as ``None``.
        """
        prompt = scene.image_prompt or scene.description
        started = time.perf_counter()
        try:
            with self._metrics.measure(RUNPOD_LATENCY):
                image = self._image_generator.generate(prompt)

            if not isinstance(image, ImageResult):
                raise TypeError(
                    "ImageGenerator.generate must return ImageResult, got "
                    f"{type(image).__name__}"
                )

            if image.url is None and image.b64:
                with self._metrics.measure(CLOUDFLARE_UPLOAD_LATENCY):
                    url = self._storage_client.upload(
                        base64.b64decode(image.b64),
                        content_type="image/png",
                    )
                image = image.model_copy(update={"url": url})

            elapsed = time.perf_counter() - started
            self._metrics.record_images_generated(1)
            self.logger.info(
                "event=image_scene_latency scene_id=%s title=%r "
                "status=ok seconds=%.3f url=%r",
                scene.id,
                scene.title,
                elapsed,
                image.url,
            )
            info = GeneratedImageInfo(
                scene_id=scene.id,
                title=scene.title,
                prompt=prompt,
                url=image.url,
                status="ok" if image.url else "Generated (no public URL)",
            )
            return (
                scene.model_copy(update={"image": image, "error": None}),
                info,
            )
        except Exception as exc:  # noqa: BLE001 - keep remaining scenes alive
            elapsed = time.perf_counter() - started
            error_message = f"{type(exc).__name__}: {exc}"
            self.logger.exception(
                "event=image_render_failed scene_id=%s title=%r "
                "seconds=%.3f error=%s",
                scene.id,
                scene.title,
                elapsed,
                error_message,
            )
            self.logger.info(
                "event=image_scene_latency scene_id=%s title=%r "
                "status=failed seconds=%.3f",
                scene.id,
                scene.title,
                elapsed,
            )
            info = GeneratedImageInfo(
                scene_id=scene.id,
                title=scene.title,
                prompt=prompt,
                url=None,
                status=f"Failed: {error_message}",
            )
            return (
                scene.model_copy(update={"image": None, "error": error_message}),
                info,
            )

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
