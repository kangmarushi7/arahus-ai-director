"""Parallel scene image generation: submit-all → poll concurrently → upload.

Preserves scene order, isolates failures, and records per-image timings for
the Sprint 4.3 pipeline report.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.models.image import ImageResult
from src.models.pipeline import GeneratedImageInfo
from src.models.storyboard import Scene
from src.monitoring.context import submit_in_pipeline_context

logger = logging.getLogger(__name__)

DEFAULT_MAX_PARALLEL_IMAGES = 6
DEFAULT_IMAGE_RETRIES = 1


@runtime_checkable
class JobImageBackend(Protocol):
    """Backend that can submit and poll image jobs independently."""

    def submit_job(self, prompt: str) -> str:
        """Enqueue ``prompt`` and return a job id."""

    def poll_job(self, job_id: str) -> dict[str, Any]:
        """Block until the job reaches a terminal state; return payload."""

    def parse_job(
        self,
        prompt: str,
        *,
        job_id: str,
        payload: dict[str, Any],
    ) -> ImageResult:
        """Map a completed payload to :class:`ImageResult`."""


@runtime_checkable
class StorageUploader(Protocol):
    """Uploads image bytes and returns a public URL."""

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Persist ``data`` and return its URL."""


@dataclass(slots=True)
class ImageJobTiming:
    """Per-scene image generation timings (milliseconds)."""

    scene_id: int
    submit_ms: float = 0.0
    queue_wait_ms: float = 0.0
    generation_ms: float = 0.0
    upload_ms: float = 0.0
    total_ms: float = 0.0
    retries: int = 0
    success: bool = True
    error: str | None = None
    job_id: str | None = None

    @property
    def total_seconds(self) -> float:
        return self.total_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParallelImageBatchResult:
    """Ordered scene/image outputs plus batch timing summary."""

    scenes: list[Scene]
    images: list[GeneratedImageInfo]
    timings: list[ImageJobTiming] = field(default_factory=list)
    total_parallel_ms: float = 0.0

    @property
    def total_parallel_seconds(self) -> float:
        return self.total_parallel_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_parallel_ms": round(self.total_parallel_ms, 3),
            "total_parallel_seconds": round(self.total_parallel_seconds, 6),
            "timings": [timing.to_dict() for timing in self.timings],
            "success_count": sum(1 for t in self.timings if t.success),
            "failure_count": sum(1 for t in self.timings if not t.success),
        }


@dataclass
class _PendingJob:
    index: int
    scene: Scene
    prompt: str
    job_id: str | None = None
    submit_ms: float = 0.0
    error: str | None = None
    retries: int = 0


class GenerateOnlyBackend:
    """Adapter for :class:`~src.pipeline.ImageGenerator` without job APIs.

    ``submit_job`` records the prompt; ``poll_job`` runs ``generate`` so
    parallel workers still overlap wall-clock time for stubs/fakes.
    """

    def __init__(self, generator: Any) -> None:
        self._generator = generator
        self._prompts: dict[str, str] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def submit_job(self, prompt: str) -> str:
        with self._lock:
            self._seq += 1
            job_id = f"local-{self._seq}"
            self._prompts[job_id] = prompt
        return job_id

    def poll_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            prompt = self._prompts.get(job_id)
        if prompt is None:
            raise KeyError(f"Unknown local job id: {job_id}")
        started = time.perf_counter()
        image = self._generator.generate(prompt)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "COMPLETED",
            "delayTime": 0,
            "executionTime": elapsed_ms,
            "_image": image,
        }

    def parse_job(
        self,
        prompt: str,
        *,
        job_id: str,
        payload: dict[str, Any],
    ) -> ImageResult:
        image = payload.get("_image")
        if isinstance(image, ImageResult):
            return image.model_copy(update={"prompt": prompt})
        raise TypeError(
            f"GenerateOnlyBackend expected ImageResult for {job_id}, "
            f"got {type(image).__name__}"
        )


class RunPodJobBackend:
    """Adapter around :class:`~src.services.runpod_client.RunPodClient`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def submit_job(self, prompt: str) -> str:
        return self._client.submit(prompt)

    def poll_job(self, job_id: str) -> dict[str, Any]:
        return self._client.poll(job_id)

    def parse_job(
        self,
        prompt: str,
        *,
        job_id: str,
        payload: dict[str, Any],
    ) -> ImageResult:
        return self._client._parse_image_result(  # noqa: SLF001
            prompt, job_id=job_id, payload=payload
        )


def resolve_image_backend(image_generator: Any) -> JobImageBackend:
    """Prefer a job-capable backend; fall back to generate-only."""
    # RunPodImageGenerator exposes the underlying client.
    runpod = getattr(image_generator, "_runpod", None)
    if runpod is not None and callable(getattr(runpod, "submit", None)):
        return RunPodJobBackend(runpod)
    if callable(getattr(image_generator, "submit_job", None)):
        return image_generator  # type: ignore[return-value]
    return GenerateOnlyBackend(image_generator)


class ParallelImageOrchestrator:
    """Submit all scene jobs immediately, then poll/upload concurrently."""

    def __init__(
        self,
        backend: JobImageBackend,
        storage: StorageUploader | None = None,
        *,
        max_parallel_images: int = DEFAULT_MAX_PARALLEL_IMAGES,
        max_retries: int = DEFAULT_IMAGE_RETRIES,
        on_progress: Any | None = None,
        on_scene_complete: Any | None = None,
        using_stub_services: bool = False,
    ) -> None:
        if max_parallel_images < 1:
            raise ValueError("max_parallel_images must be >= 1")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._backend = backend
        self._storage = storage
        self._max_parallel = int(max_parallel_images)
        self._max_retries = int(max_retries)
        self._on_progress = on_progress
        self._on_scene_complete = on_scene_complete
        self._using_stub_services = using_stub_services

    def render(
        self,
        scenes: list[Scene],
    ) -> ParallelImageBatchResult:
        """Render ``scenes`` in parallel; return results in input order."""
        if not scenes:
            return ParallelImageBatchResult(scenes=[], images=[], timings=[])

        wall_started = time.perf_counter()
        pending = [
            _PendingJob(
                index=index,
                scene=scene,
                prompt=(scene.image_prompt or scene.description or "").strip(),
            )
            for index, scene in enumerate(scenes)
        ]

        self._emit(
            f"Submitting {len(pending)} image jobs "
            f"(max_parallel_images={self._max_parallel})…"
        )
        self._submit_all(pending)

        results: list[tuple[Scene, GeneratedImageInfo, ImageJobTiming] | None] = [
            None
        ] * len(pending)

        # First pass: poll + upload everything that submitted successfully.
        to_process = [job for job in pending if job.job_id and not job.error]
        self._process_jobs(to_process, results)

        # Mark submit-time failures.
        for job in pending:
            if results[job.index] is not None:
                continue
            if job.error or not job.job_id:
                results[job.index] = self._failure_result(
                    job,
                    error=job.error or "Image job submit failed",
                    submit_ms=job.submit_ms,
                )
                self._notify_scene_complete(results[job.index][1])

        # Retry only failed scenes (re-submit + poll).
        for attempt in range(1, self._max_retries + 1):
            failed_indices = [
                index
                for index, item in enumerate(results)
                if item is not None and not item[2].success
            ]
            if not failed_indices:
                break
            self._emit(
                f"Retrying {len(failed_indices)} failed image(s) "
                f"(attempt {attempt}/{self._max_retries})…"
            )
            retry_jobs: list[_PendingJob] = []
            for index in failed_indices:
                source = pending[index]
                retry = _PendingJob(
                    index=index,
                    scene=source.scene,
                    prompt=source.prompt,
                    retries=attempt,
                )
                retry_jobs.append(retry)
            self._submit_all(retry_jobs)
            # Clear previous failure slots before writing retries.
            for job in retry_jobs:
                results[job.index] = None
            ok_jobs = [job for job in retry_jobs if job.job_id and not job.error]
            self._process_jobs(ok_jobs, results)
            for job in retry_jobs:
                if results[job.index] is not None:
                    continue
                results[job.index] = self._failure_result(
                    job,
                    error=job.error or "Image job retry submit failed",
                    submit_ms=job.submit_ms,
                )

        # Defensive fill for any missing slot.
        for index, item in enumerate(results):
            if item is None:
                results[index] = self._failure_result(
                    pending[index],
                    error="Image job produced no result",
                )

        ordered = [item for item in results if item is not None]
        total_parallel_ms = (time.perf_counter() - wall_started) * 1000.0
        return ParallelImageBatchResult(
            scenes=[item[0] for item in ordered],
            images=[item[1] for item in ordered],
            timings=[item[2] for item in ordered],
            total_parallel_ms=total_parallel_ms,
        )

    def _submit_all(self, jobs: list[_PendingJob]) -> None:
        """Submit every job as quickly as possible (bounded parallelism)."""
        workers = min(self._max_parallel, max(1, len(jobs)))

        def _submit_one(job: _PendingJob) -> None:
            if not job.prompt:
                job.error = "Scene has empty image prompt"
                return
            started = time.perf_counter()
            try:
                job.job_id = self._backend.submit_job(job.prompt)
            except Exception as exc:  # noqa: BLE001 - isolate submit failures
                job.error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "event=image_submit_failed scene_id=%s error=%s",
                    job.scene.id,
                    job.error,
                )
            finally:
                job.submit_ms = (time.perf_counter() - started) * 1000.0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                submit_in_pipeline_context(executor, _submit_one, job) for job in jobs
            ]
            for future in as_completed(futures):
                future.result()

        for job in jobs:
            if job.job_id:
                self._emit(
                    f"  Submitted scene {job.scene.id}: {job.scene.title} "
                    f"(job={job.job_id}, {job.submit_ms:.0f}ms)"
                )

    def _process_jobs(
        self,
        jobs: list[_PendingJob],
        results: list[tuple[Scene, GeneratedImageInfo, ImageJobTiming] | None],
    ) -> None:
        if not jobs:
            return
        workers = min(self._max_parallel, max(1, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map: dict[Future[tuple[Scene, GeneratedImageInfo, ImageJobTiming]], _PendingJob] = {
                submit_in_pipeline_context(executor, self._poll_and_upload, job): job
                for job in jobs
            }
            for future in as_completed(future_map):
                job = future_map[future]
                try:
                    results[job.index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
                    logger.exception(
                        "event=image_worker_crashed scene_id=%s error=%s",
                        job.scene.id,
                        error,
                    )
                    results[job.index] = self._failure_result(
                        job, error=error, submit_ms=job.submit_ms
                    )
                item = results[job.index]
                if item is not None:
                    _scene, info, timing = item
                    self._notify_scene_complete(info)
                    self._emit(
                        f"  Completed scene {job.scene.id}: {info.status}"
                        + (f" ({timing.total_seconds:.0f}s)" if timing.total_ms else "")
                        + (f" → {info.url}" if info.url else "")
                    )

    def _poll_and_upload(
        self,
        job: _PendingJob,
    ) -> tuple[Scene, GeneratedImageInfo, ImageJobTiming]:
        assert job.job_id is not None
        scene = job.scene
        timing = ImageJobTiming(
            scene_id=scene.id,
            submit_ms=job.submit_ms,
            retries=job.retries,
            job_id=job.job_id,
        )
        wall_started = time.perf_counter()
        try:
            poll_started = time.perf_counter()
            payload = self._backend.poll_job(job.job_id)
            poll_ms = (time.perf_counter() - poll_started) * 1000.0
            timing.queue_wait_ms, timing.generation_ms = _split_poll_timing(
                payload, poll_ms
            )

            image = self._backend.parse_job(
                job.prompt, job_id=job.job_id, payload=payload
            )
            if not isinstance(image, ImageResult):
                raise TypeError(
                    "parse_job must return ImageResult, got "
                    f"{type(image).__name__}"
                )

            if (not image.url or not image.url.strip()) and image.b64:
                upload_started = time.perf_counter()
                if self._storage is None:
                    raise RuntimeError("Image has base64 data but no storage client")
                url = self._storage.upload(
                    base64.b64decode(image.b64),
                    content_type="image/png",
                )
                timing.upload_ms = (time.perf_counter() - upload_started) * 1000.0
                image = image.model_copy(update={"url": url, "b64": None})

            timing.total_ms = (time.perf_counter() - wall_started) * 1000.0 + job.submit_ms
            timing.success = True
            if image.url:
                status = "ok"
            elif self._using_stub_services:
                status = "stub/unavailable"
            else:
                status = "Generated (no public URL)"
            info = GeneratedImageInfo(
                scene_id=scene.id,
                title=scene.title,
                prompt=job.prompt,
                url=image.url,
                status=status,
            )
            logger.info(
                "event=image_scene_timing scene_id=%s job_id=%s submit_ms=%.1f "
                "queue_ms=%.1f generation_ms=%.1f upload_ms=%.1f total_ms=%.1f "
                "retries=%s status=ok",
                scene.id,
                job.job_id,
                timing.submit_ms,
                timing.queue_wait_ms,
                timing.generation_ms,
                timing.upload_ms,
                timing.total_ms,
                timing.retries,
            )
            return (
                scene.model_copy(update={"image": image, "error": None}),
                info,
                timing,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            timing.success = False
            timing.error = error
            timing.total_ms = (time.perf_counter() - wall_started) * 1000.0 + job.submit_ms
            logger.exception(
                "event=image_scene_failed scene_id=%s job_id=%s error=%s",
                scene.id,
                job.job_id,
                error,
            )
            return self._failure_result(
                job, error=error, submit_ms=job.submit_ms, timing=timing
            )

    def _failure_result(
        self,
        job: _PendingJob,
        *,
        error: str,
        submit_ms: float = 0.0,
        timing: ImageJobTiming | None = None,
    ) -> tuple[Scene, GeneratedImageInfo, ImageJobTiming]:
        scene = job.scene
        final = timing or ImageJobTiming(
            scene_id=scene.id,
            submit_ms=submit_ms or job.submit_ms,
            retries=job.retries,
            job_id=job.job_id,
            success=False,
            error=error,
            total_ms=submit_ms or job.submit_ms,
        )
        final.success = False
        final.error = error
        info = GeneratedImageInfo(
            scene_id=scene.id,
            title=scene.title,
            prompt=job.prompt,
            url=None,
            status=f"Failed: {error}",
        )
        return (
            scene.model_copy(update={"image": None, "error": error}),
            info,
            final,
        )

    def _emit(self, message: str) -> None:
        if self._on_progress is None:
            return
        try:
            self._on_progress(message)
        except Exception:  # noqa: BLE001
            logger.exception("image progress callback failed")

    def _notify_scene_complete(self, info: GeneratedImageInfo) -> None:
        if self._on_scene_complete is None:
            return
        try:
            self._on_scene_complete(info)
        except Exception:  # noqa: BLE001
            logger.exception("image scene-complete callback failed")


def _split_poll_timing(
    payload: dict[str, Any],
    poll_elapsed_ms: float,
) -> tuple[float, float]:
    """Derive queue-wait and generation ms from RunPod payload or wall poll time."""
    delay = payload.get("delayTime")
    execution = payload.get("executionTime")
    queue_ms = float(delay) if isinstance(delay, (int, float)) else 0.0
    generation_ms = (
        float(execution) if isinstance(execution, (int, float)) else 0.0
    )
    if queue_ms <= 0 and generation_ms <= 0:
        # No provider metrics — attribute full poll wait to generation.
        return 0.0, max(0.0, poll_elapsed_ms)
    if generation_ms <= 0 and queue_ms > 0:
        generation_ms = max(0.0, poll_elapsed_ms - queue_ms)
    if queue_ms <= 0 and generation_ms > 0:
        queue_ms = max(0.0, poll_elapsed_ms - generation_ms)
    return queue_ms, generation_ms


def format_image_generation_report(
    timings: list[ImageJobTiming],
    *,
    total_parallel_ms: float,
) -> str:
    """Render the Sprint 4.3 Image Generation console block."""
    lines = [
        "Image Generation",
        "---------------",
    ]
    for timing in sorted(timings, key=lambda item: item.scene_id):
        seconds = int(round(timing.total_seconds))
        suffix = "" if timing.success else " (failed)"
        lines.append(f"Scene {timing.scene_id}   {seconds}s{suffix}")
    lines.append("")
    parallel_s = int(round(total_parallel_ms / 1000.0))
    lines.append(f"Total Parallel Time: {parallel_s}s")
    return "\n".join(lines)
