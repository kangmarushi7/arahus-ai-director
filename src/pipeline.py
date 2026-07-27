"""Orchestration for the topic-to-storyboard workflow."""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

from src.agents.director import DirectorAgent
from src.agents.prompt import PromptAgent
from src.agents.research import ResearchAgent
from src.agents.review import ReviewAgent
from src.characters import (
    format_character_bible,
    persist_character_profiles,
    profiles_from_research,
)
from src.config import get_settings
from src.domain import (
    ConfigLoader,
    DomainRegistry,
    DomainService,
    LLMDomainDetector,
)
from src.domain.service import DomainServiceError
from src.events import (
    DirectorCompleted,
    Event,
    EventBus,
    ImageGenerated,
    PromptCompleted,
    ResearchCompleted,
    ReviewCompleted,
)
from src.models.context import PipelineContext
from src.models.image import ImageResult
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.monitoring.metrics import (
    CLOUDFLARE_UPLOAD_LATENCY,
    DIRECTOR_LATENCY,
    PROMPT_LATENCY,
    RESEARCH_LATENCY,
    REVIEW_LATENCY,
    RUNPOD_LATENCY,
    STAGE_DIRECTOR,
    STAGE_DOMAIN_DETECTION,
    STAGE_PROMPT,
    STAGE_RESEARCH,
    STAGE_REVIEW,
    TOTAL_LATENCY,
    MetricsCollector,
)
from src.monitoring.pipeline_metrics import PipelineReport
from src.monitoring.pipeline_profiler import PipelineProfiler
from src.monitoring.report import report_to_dashboard_metrics
from src.progress import ProgressCallback, ProgressReporter
from src.prompt import PromptComposer
from src.prompt.optimizer import PromptOptimizer
from src.services.llm import LLMClient
from src.services.llm_factory import create_task_llm
from src.services.parallel_images import (
    ParallelImageOrchestrator,
    resolve_image_backend,
)

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
    """Runs domain detection, research, director, prompt, review, and images.

    By default each LLM-backed agent receives its own client from
    :func:`create_task_llm`, using router/env task routes. Optional client
    overrides keep the pipeline testable with fakes. Public :meth:`generate`
    signature is unchanged.
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
        domain_service: DomainService | None = None,
        prompt_composer: PromptComposer | None = None,
        domain_llm: LLMClient | None = None,
        max_parallel_images: int | None = None,
        event_bus: EventBus | None = None,
        using_stub_services: bool = False,
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
            domain_service: Optional domain intelligence facade.
            prompt_composer: Optional deterministic prompt composer.
            domain_llm: Optional LLM used only for domain detection when
                ``domain_service`` is not injected.
            max_parallel_images: Max concurrent image jobs (default from
                ``MAX_PARALLEL_IMAGES`` / ``IMAGE_MAX_WORKERS``, usually 4).
            event_bus: Optional in-process event bus for stage notifications.
            using_stub_services: When ``True``, image statuses reflect stub mode.
        """
        settings = get_settings()
        retries = (
            settings.pipeline.max_storyboard_retries
            if max_storyboard_retries is None
            else max_storyboard_retries
        )
        if retries < 0:
            raise ValueError("max_storyboard_retries cannot be negative")

        parallel = (
            settings.pipeline.image_max_workers
            if max_parallel_images is None
            else int(max_parallel_images)
        )
        if parallel < 1:
            raise ValueError("max_parallel_images must be >= 1")

        self.logger = logging.getLogger(self.__class__.__name__)
        self._image_generator = image_generator
        self._storage_client = storage_client
        self._max_storyboard_retries = retries
        self._max_parallel_images = parallel
        self._metrics = metrics or MetricsCollector()
        self._event_bus = event_bus
        self._using_stub_services = using_stub_services

        self._research_llm = research_llm or create_task_llm("research")
        self._director_llm = director_llm or create_task_llm("director")
        self._prompt_llm = prompt_llm or create_task_llm("prompt")
        self._review_llm = review_llm or create_task_llm("review")
        self._domain_llm = domain_llm or create_task_llm("domain")

        self._prompt_composer = prompt_composer or PromptComposer()
        self._config_loader = ConfigLoader()
        self._domain_service = domain_service or DomainService(
            detector=LLMDomainDetector(self._domain_llm),
            registry=DomainRegistry(),
            config_loader=self._config_loader,
        )

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
            prompt_composer=self._prompt_composer,
            config_loader=self._config_loader,
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

        Captures domain detection, research, director plan, approved storyboard,
        review, image statuses, and metrics for the studio UI.

        Args:
            topic: Subject or event to visualize.
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
        settings = get_settings()
        monitoring_enabled = settings.monitoring.enabled
        self._reporter = ProgressReporter(callback=progress_callback)
        self._bind_step_loggers()
        self._emit(f"Pipeline started for topic: {cleaned_topic}", progress=0.01)
        self._metrics.reset()
        profiler = PipelineProfiler(
            self._metrics,
            topic=cleaned_topic,
            log=self.logger,
            print_table=monitoring_enabled,
            print_cost_report=monitoring_enabled,
        )
        profiler.start()
        started = time.perf_counter()
        stage_timings: dict[str, float] = {
            "domain_seconds": 0.0,
            "research_seconds": 0.0,
            "director_seconds": 0.0,
            "prompt_seconds": 0.0,
            "review_seconds": 0.0,
            "image_seconds": 0.0,
        }
        pipeline_context: PipelineContext | None = None
        character_bible = ""
        run_error: str | None = None
        research: ResearchResult | None = None
        plan: DirectorPlan | None = None
        review: ReviewResult | None = None
        final_storyboard: Storyboard | None = None
        images: list[GeneratedImageInfo] = []

        try:
            with profiler.bind():
                self._begin_stage("Domain")
                self._emit("Stage 1/6 — Domain…", progress=0.02)
                stage_started = time.perf_counter()
                try:
                    with profiler.measure(STAGE_DOMAIN_DETECTION):
                        domain_info = self._domain_service.detect(cleaned_topic)
                        prompt_context = self._domain_service.get_prompt_context(
                            domain_info.domain
                        )
                except DomainServiceError as exc:
                    raise ValueError(f"Domain detection failed: {exc}") from exc
                stage_timings["domain_seconds"] = time.perf_counter() - stage_started
                self._complete_stage("Domain")

                pipeline_context = PipelineContext(
                    topic=cleaned_topic,
                    domain_info=domain_info,
                    prompt_context=prompt_context,
                )
                self._log_domain_selection(pipeline_context)

                self._begin_stage("Research")
                self._emit(
                    "Stage 2/6 — Research Agent: gathering reference material…",
                    progress=0.05,
                )
                stage_started = time.perf_counter()
                with profiler.measure(STAGE_RESEARCH):
                    research = self._research_agent.run(
                        cleaned_topic,
                        domain_info=pipeline_context.domain_info,
                    )
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

                profiles = profiles_from_research(research)
                persist_character_profiles(profiles)
                character_bible = format_character_bible(profiles)
                self._publish(
                    ResearchCompleted(
                        topic=cleaned_topic,
                        time_period=research.time_period,
                        location=research.location,
                    )
                )

                self._begin_stage("Director")
                self._emit(
                    "Stage 3/6 — Director Agent: planning four scenes…",
                    progress=0.25,
                )
                stage_started = time.perf_counter()
                with profiler.measure(STAGE_DIRECTOR):
                    plan = self._director_agent.run(
                        cleaned_topic,
                        research,
                        domain_info=pipeline_context.domain_info,
                        character_bible=character_bible,
                    )
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
                self._publish(
                    DirectorCompleted(
                        topic=cleaned_topic,
                        scene_count=len(plan.scenes),
                    )
                )

                self._emit(
                    "Stage 4–5/6 — Prompt + Review Agents…",
                    progress=0.45,
                )
                storyboard, review, prompt_seconds, review_seconds = (
                    self._generate_approved_storyboard(
                        plan,
                        research,
                        context=pipeline_context,
                        profiler=profiler,
                        character_bible=character_bible,
                    )
                )
                stage_timings["prompt_seconds"] = prompt_seconds
                stage_timings["review_seconds"] = review_seconds
                self._emit(
                    "Storyboard approved "
                    f"(score={review.overall_score:.0f}, "
                    f"prompt={prompt_seconds:.1f}s, review={review_seconds:.1f}s)",
                    progress=0.72,
                )

                max_cost = settings.pipeline.max_cost_usd
                spent = profiler.cost_tracker.total_llm_cost
                if max_cost > 0 and spent >= max_cost:
                    warning = (
                        f"Cost cap reached (${spent:.4f} >= ${max_cost:.4f}); "
                        "skipping image generation"
                    )
                    self.logger.warning("event=cost_cap_skip_images %s", warning)
                    self._emit(warning, progress=0.75)
                    images = [
                        GeneratedImageInfo(
                            scene_id=scene.id,
                            title=scene.title,
                            prompt=scene.image_prompt or scene.description,
                            url=None,
                            status=f"Skipped: cost cap (${max_cost:.2f})",
                        )
                        for scene in storyboard.scenes
                    ]
                    final_storyboard = storyboard
                    stage_timings["image_seconds"] = 0.0
                else:
                    self._begin_stage("Images")
                    self._emit("Stage 6/6 — Image generation…", progress=0.75)
                    stage_started = time.perf_counter()
                    final_storyboard, images = self._render_storyboard_images(
                        storyboard,
                        topic=cleaned_topic,
                        profiler=profiler,
                    )
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

                pipeline_report = (
                    profiler.pipeline_report or profiler.build_pipeline_report()
                )
                result = PipelineResult(
                    topic=cleaned_topic,
                    research=research,
                    plan=plan,
                    storyboard=final_storyboard,
                    review=review,
                    images=images,
                    metrics=self._studio_metrics_snapshot(
                        stage_timings,
                        profiler_report=profiler.report,
                        pipeline_report=pipeline_report,
                    ),
                    domain_info=pipeline_context.domain_info,
                    prompt_context=pipeline_context.prompt_context,
                    context=pipeline_context,
                    using_stub_services=self._using_stub_services,
                    character_bible=character_bible,
                )
                self._maybe_persist_result(result)
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            profiler.finish(error=run_error)
            export_path = settings.monitoring.export_path.strip()
            if export_path:
                try:
                    profiler.export_json(export_path)
                except Exception as exc:  # noqa: BLE001 - export is best-effort
                    self.logger.warning(
                        "event=metrics_export_failed path=%r error=%s",
                        export_path,
                        exc,
                    )
            profiler.log_report()
            self._unbind_step_loggers()
            self._reporter = None

        assert research is not None
        assert plan is not None
        assert review is not None
        assert final_storyboard is not None
        pipeline_report = profiler.pipeline_report or profiler.build_pipeline_report()
        return PipelineResult(
            topic=cleaned_topic,
            research=research,
            plan=plan,
            storyboard=final_storyboard,
            review=review,
            images=images,
            metrics=self._studio_metrics_snapshot(
                stage_timings,
                profiler_report=profiler.report,
                pipeline_report=pipeline_report,
            ),
            domain_info=(
                pipeline_context.domain_info if pipeline_context is not None else None
            ),
            prompt_context=(
                pipeline_context.prompt_context if pipeline_context is not None else None
            ),
            context=pipeline_context,
            using_stub_services=self._using_stub_services,
            character_bible=character_bible,
        )

    def _maybe_persist_result(self, result: PipelineResult) -> None:
        """Persist pipeline artifacts when configured and DATABASE_URL is set."""
        settings = get_settings()
        db_url = settings.database.url.get_secret_value().strip()
        if not settings.pipeline.persist_pipeline_runs or not db_url:
            return
        try:
            from src.playground.persistence import sync_pipeline_result

            sync_pipeline_result(result, metrics=result.metrics)
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            self.logger.warning(
                "event=pipeline_persist_skipped topic=%r error=%s",
                result.topic,
                exc,
            )

    def _publish(self, event: Event) -> None:
        """Publish ``event`` when an event bus is configured."""
        bus = self._event_bus
        if bus is None:
            return
        try:
            bus.publish(event)
        except Exception as exc:  # noqa: BLE001 - do not fail the pipeline
            self.logger.warning(
                "event=event_bus_publish_failed type=%s error=%s",
                type(event).__name__,
                exc,
            )

    def _log_domain_selection(self, context: PipelineContext) -> None:
        """Emit operator logs for domain / style / camera selection."""
        info = context.domain_info
        prompt_ctx = context.prompt_context
        self.logger.info(
            "event=domain_detected topic=%r domain=%s confidence=%.3f "
            "style_pack=%r camera_preset=%r lighting_preset=%r",
            context.topic,
            info.domain.value,
            info.confidence,
            prompt_ctx.style[:120],
            prompt_ctx.camera[:120],
            prompt_ctx.lighting[:120],
        )
        self._emit(
            f"Detected domain={info.domain.value} "
            f"(confidence={info.confidence:.2f})",
            progress=0.04,
        )
        self._emit(f"Selected style pack: {prompt_ctx.style[:160]}")
        self._emit(f"Selected camera preset: {prompt_ctx.camera[:160]}")

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
        *,
        context: PipelineContext,
        profiler: PipelineProfiler,
        character_bible: str = "",
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
        settings = get_settings()
        optimizer = (
            PromptOptimizer(composer=self._prompt_composer)
            if settings.pipeline.prompt_optimizer_enabled
            else None
        )

        for attempt in range(1, total_attempts + 1):
            # Prompt/review share 0.45 → 0.72 of the bar across attempts.
            attempt_span = 0.27 / total_attempts
            attempt_base = 0.45 + (attempt - 1) * attempt_span

            self._begin_stage("Prompt")
            self._set_stage("Prompt", 0.15)
            self._emit(
                f"Prompt Agent attempt {attempt}/{total_attempts}: "
                "writing scene content and composing FLUX prompts…",
                progress=attempt_base,
            )
            stage_started = time.perf_counter()
            with profiler.measure(STAGE_PROMPT):
                storyboard = self._prompt_agent.run(
                    plan,
                    research,
                    domain_info=context.domain_info,
                    prompt_context=context.prompt_context,
                    character_bible=character_bible,
                )
                if optimizer is not None:
                    storyboard = self._optimize_storyboard_prompts(
                        storyboard,
                        context.prompt_context,
                        optimizer=optimizer,
                    )
            prompt_seconds += time.perf_counter() - stage_started
            self._complete_stage("Prompt")
            self._publish(
                PromptCompleted(
                    topic=plan.topic,
                    scene_count=len(storyboard.scenes),
                )
            )
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
            with profiler.measure(STAGE_REVIEW):
                review = self._review_agent.run(
                    storyboard,
                    domain_info=context.domain_info,
                )
            review_seconds += time.perf_counter() - stage_started
            last_review = review
            self._complete_stage("Review")
            self._publish(
                ReviewCompleted(
                    topic=plan.topic,
                    overall_score=review.overall_score,
                    approved=review.approved,
                )
            )

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
                f"domain={review.domain_accuracy:.0f} "
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
                profiler.record_storyboard_retry(1)
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

    def _optimize_storyboard_prompts(
        self,
        storyboard: Storyboard,
        prompt_context: object,
        *,
        optimizer: PromptOptimizer,
    ) -> Storyboard:
        """Replace each scene's image_prompt with the best optimizer variant."""
        from src.domain.prompt_context import DomainPromptContext

        if not isinstance(prompt_context, DomainPromptContext):
            return storyboard

        optimized: list[Scene] = []
        for scene in storyboard.scenes:
            # Prefer the PromptAgent subject lead-in over the scene title so
            # optimizer variants preserve composed meaning.
            subject_hint: str | None = None
            if scene.image_prompt and scene.image_prompt.strip():
                subject_hint = scene.image_prompt.split(",", 1)[0].strip() or None
            try:
                variants = optimizer.optimize(
                    scene,
                    prompt_context,
                    subject=subject_hint,
                )
            except Exception as exc:  # noqa: BLE001 - keep original prompt
                self.logger.warning(
                    "event=prompt_optimize_skipped scene_id=%s error=%s",
                    scene.id,
                    exc,
                )
                optimized.append(scene)
                continue
            if not variants:
                optimized.append(scene)
                continue
            best = variants[0]
            optimized.append(
                scene.model_copy(update={"image_prompt": best.positive_prompt})
            )
            self.logger.info(
                "event=prompt_optimized scene_id=%s style=%s score=%s",
                scene.id,
                best.style_name,
                best.metadata.get("score"),
            )
        return storyboard.model_copy(update={"scenes": optimized})

    def _render_storyboard_images(
        self,
        storyboard: Storyboard,
        *,
        topic: str,
        profiler: PipelineProfiler | None = None,
    ) -> tuple[Storyboard, list[GeneratedImageInfo]]:
        """Submit all scene jobs, then poll/upload concurrently.

        Uses :class:`~src.services.parallel_images.ParallelImageOrchestrator`
        so every job is submitted immediately and polled with
        ``max_parallel_images`` workers. Scene order is preserved; one failure
        does not cancel the others (failed scenes are retried individually).

        Args:
            storyboard: Approved storyboard with image prompts.
            topic: Pipeline topic used for image-generated events.
            profiler: Optional profiler that receives image timing breakdowns.

        Returns:
            A complete storyboard (scenes in original order, each with
            ``image`` and/or ``error``) plus studio image-info rows.
        """
        scenes = list(storyboard.scenes)
        scene_count = len(scenes)
        if scene_count == 0:
            return storyboard, []

        max_parallel = min(scene_count, self._max_parallel_images)
        self._emit(
            f"Rendering {scene_count} scenes in parallel "
            f"(max_parallel_images={max_parallel})…"
        )
        self._set_stage("Images", 0.1)

        completed = {"n": 0}

        def _on_progress(message: str) -> None:
            self._emit(message)

        def _on_scene_done(info: GeneratedImageInfo) -> None:
            completed["n"] += 1
            self._publish(
                ImageGenerated(
                    topic=topic,
                    scene_id=info.scene_id,
                    prompt=info.prompt,
                    url=info.url,
                )
            )
            if info.url:
                self._metrics.record_images_generated(1)
            self._set_stage("Images", 0.2 + (0.8 * (completed["n"] / scene_count)))
            progress = 0.80 + (0.18 * (completed["n"] / scene_count))
            self._emit(
                f"Completed image {info.scene_id}/{scene_count}... "
                f"({info.status}"
                + (f" → {info.url}" if info.url else "")
                + ")",
                progress=progress,
            )

        backend = resolve_image_backend(self._image_generator)
        orchestrator = ParallelImageOrchestrator(
            backend,
            self._storage_client,
            max_parallel_images=max_parallel,
            max_retries=1,
            on_progress=_on_progress,
            on_scene_complete=_on_scene_done,
            using_stub_services=self._using_stub_services,
        )

        with self._metrics.measure(RUNPOD_LATENCY):
            batch = orchestrator.render(scenes)

        if profiler is not None:
            profiler.record_image_batch(
                timings=[timing.to_dict() for timing in batch.timings],
                total_parallel_ms=batch.total_parallel_ms,
            )

        if len(batch.scenes) != scene_count:
            raise RuntimeError(
                "Parallel image stage lost scenes: "
                f"expected {scene_count}, got {len(batch.scenes)}"
            )

        return (
            storyboard.model_copy(update={"scenes": batch.scenes}),
            batch.images,
        )

    def _studio_metrics_snapshot(
        self,
        stage_timings: dict[str, float] | None = None,
        *,
        profiler_report: object | None = None,
        pipeline_report: object | None = None,
    ) -> dict[str, object]:
        """Flatten metrics into the shape expected by the Streamlit dashboard."""
        snap = self._metrics.snapshot()
        latency = snap.get("latency", {})
        tokens = snap.get("tokens", {})
        timings = stage_timings or {}
        profiler_payload: dict[str, object] = {}
        if profiler_report is not None and hasattr(profiler_report, "to_dict"):
            profiler_payload = profiler_report.to_dict()  # type: ignore[assignment]

        report_fields: dict[str, object] = {}
        if isinstance(pipeline_report, PipelineReport):
            report_fields = report_to_dashboard_metrics(pipeline_report)
        elif pipeline_report is not None and hasattr(pipeline_report, "to_dict"):
            report_fields = {
                "pipeline_report": pipeline_report.to_dict(),  # type: ignore[union-attr]
            }

        payload: dict[str, object] = {
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
            "domain_seconds": round(timings.get("domain_seconds", 0.0), 6),
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
            "profiler": profiler_payload,
            "using_stub_services": self._using_stub_services,
            "raw": snap,
        }
        # Sprint 4.2 fields overlay timing/cost keys when a full report exists.
        payload.update(report_fields)
        payload["using_stub_services"] = self._using_stub_services
        return payload
