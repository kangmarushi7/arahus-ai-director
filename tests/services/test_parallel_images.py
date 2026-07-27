"""Integration tests for parallel image generation."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.models.image import ImageResult
from src.models.storyboard import Scene
from src.monitoring.pipeline_metrics import PipelineReport
from src.monitoring.report import format_pipeline_report
from src.services.parallel_images import (
    ImageJobTiming,
    ParallelImageOrchestrator,
    format_image_generation_report,
)


class _ConcurrentBackend:
    """Fake backend that sleeps during poll to prove overlapping execution."""

    def __init__(
        self,
        *,
        poll_seconds: float = 0.25,
        fail_once_scene_ids: set[int] | None = None,
    ) -> None:
        self.poll_seconds = poll_seconds
        self.fail_once_scene_ids = fail_once_scene_ids or set()
        self._failed_once: set[int] = set()
        self.submit_times: dict[str, float] = {}
        self.poll_started: dict[str, float] = {}
        self.poll_active = 0
        self.max_poll_active = 0
        self._lock = threading.Lock()
        self._seq = 0
        self._prompts: dict[str, str] = {}
        self._scene_for_job: dict[str, int] = {}
        self.submit_order: list[str] = []

    def submit_job(self, prompt: str) -> str:
        with self._lock:
            self._seq += 1
            job_id = f"job-{self._seq}"
            self._prompts[job_id] = prompt
            scene_id = int(prompt.split("|", 1)[0].removeprefix("scene-"))
            self._scene_for_job[job_id] = scene_id
            self.submit_times[job_id] = time.perf_counter()
            self.submit_order.append(job_id)
        return job_id

    def poll_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self.poll_started[job_id] = time.perf_counter()
            self.poll_active += 1
            self.max_poll_active = max(self.max_poll_active, self.poll_active)
            scene_id = self._scene_for_job[job_id]
            should_fail = (
                scene_id in self.fail_once_scene_ids
                and scene_id not in self._failed_once
            )
            if should_fail:
                self._failed_once.add(scene_id)
        try:
            if should_fail:
                time.sleep(0.01)
                raise RuntimeError(f"simulated failure scene {scene_id}")
            time.sleep(self.poll_seconds)
            return {
                "status": "COMPLETED",
                "delayTime": 10,
                "executionTime": self.poll_seconds * 1000.0,
                "output": {"url": f"https://example.test/{job_id}.png"},
            }
        finally:
            with self._lock:
                self.poll_active -= 1

    def parse_job(
        self,
        prompt: str,
        *,
        job_id: str,
        payload: dict[str, Any],
    ) -> ImageResult:
        output = payload.get("output") or {}
        url = output.get("url") if isinstance(output, dict) else None
        return ImageResult(prompt=prompt, url=url)


class _CountingStorage:
    def __init__(self) -> None:
        self.uploads = 0
        self.upload_started: list[float] = []

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        self.uploads += 1
        self.upload_started.append(time.perf_counter())
        return f"https://cdn.example/{self.uploads}.png"


def _scenes(n: int = 4) -> list[Scene]:
    return [
        Scene(
            id=i,
            title=f"Scene {i}",
            description=f"Description for scene {i}",
            image_prompt=f"scene-{i}|cinematic prompt {i}",
        )
        for i in range(1, n + 1)
    ]


class TestParallelImageOrchestrator:
    def test_four_scenes_poll_concurrently(self) -> None:
        backend = _ConcurrentBackend(poll_seconds=0.3)
        orch = ParallelImageOrchestrator(
            backend,
            max_parallel_images=4,
            max_retries=0,
        )
        wall_started = time.perf_counter()
        batch = orch.render(_scenes(4))
        wall = time.perf_counter() - wall_started

        assert len(batch.scenes) == 4
        assert [s.id for s in batch.scenes] == [1, 2, 3, 4]
        assert all(info.url for info in batch.images)
        assert backend.max_poll_active >= 4
        # Sequential would be ~1.2s; parallel should be closer to ~0.3s (+overhead).
        assert wall < 0.9
        assert batch.total_parallel_ms < 900
        # All submits happened before any poll finished (submit-all semantics).
        assert len(backend.submit_order) == 4
        last_submit = max(backend.submit_times.values())
        first_poll_endish = min(backend.poll_started.values()) + 0.05
        assert last_submit <= first_poll_endish + 0.2

    def test_preserves_order_with_staggered_completion(self) -> None:
        class SlowFirstBackend(_ConcurrentBackend):
            def poll_job(self, job_id: str) -> dict[str, Any]:
                scene_id = self._scene_for_job[job_id]
                delay = 0.35 if scene_id == 1 else 0.05
                with self._lock:
                    self.poll_started[job_id] = time.perf_counter()
                    self.poll_active += 1
                    self.max_poll_active = max(self.max_poll_active, self.poll_active)
                try:
                    time.sleep(delay)
                    return {
                        "status": "COMPLETED",
                        "delayTime": 1,
                        "executionTime": delay * 1000.0,
                        "output": {"url": f"https://example.test/{job_id}.png"},
                    }
                finally:
                    with self._lock:
                        self.poll_active -= 1

        backend = SlowFirstBackend()
        batch = ParallelImageOrchestrator(
            backend, max_parallel_images=4, max_retries=0
        ).render(_scenes(4))
        assert [s.id for s in batch.scenes] == [1, 2, 3, 4]
        assert [img.scene_id for img in batch.images] == [1, 2, 3, 4]

    def test_partial_failure_continues_others_and_retries(self) -> None:
        backend = _ConcurrentBackend(poll_seconds=0.05, fail_once_scene_ids={2})
        batch = ParallelImageOrchestrator(
            backend,
            max_parallel_images=4,
            max_retries=1,
        ).render(_scenes(4))

        assert len(batch.scenes) == 4
        by_id = {s.id: s for s in batch.scenes}
        assert by_id[1].error is None and by_id[1].image is not None
        assert by_id[3].error is None and by_id[3].image is not None
        assert by_id[4].error is None and by_id[4].image is not None
        # Scene 2 fails once then succeeds on retry.
        assert by_id[2].error is None and by_id[2].image is not None
        scene2_timing = next(t for t in batch.timings if t.scene_id == 2)
        assert scene2_timing.retries == 1
        assert scene2_timing.success is True

    def test_tracks_per_image_timings(self) -> None:
        backend = _ConcurrentBackend(poll_seconds=0.05)
        batch = ParallelImageOrchestrator(
            backend, max_parallel_images=4, max_retries=0
        ).render(_scenes(4))
        assert len(batch.timings) == 4
        for timing in batch.timings:
            assert timing.submit_ms >= 0
            assert timing.generation_ms > 0 or timing.queue_wait_ms >= 0
            assert timing.total_ms > 0
            assert timing.success is True

    def test_upload_as_jobs_finish(self) -> None:
        class B64Backend(_ConcurrentBackend):
            def poll_job(self, job_id: str) -> dict[str, Any]:
                with self._lock:
                    self.poll_started[job_id] = time.perf_counter()
                    self.poll_active += 1
                    self.max_poll_active = max(self.max_poll_active, self.poll_active)
                try:
                    time.sleep(self.poll_seconds)
                    return {
                        "status": "COMPLETED",
                        "delayTime": 5,
                        "executionTime": 20,
                        "output": {"b64": "aGVsbG8="},  # "hello"
                    }
                finally:
                    with self._lock:
                        self.poll_active -= 1

            def parse_job(
                self,
                prompt: str,
                *,
                job_id: str,
                payload: dict[str, Any],
            ) -> ImageResult:
                return ImageResult(prompt=prompt, b64="aGVsbG8=")

        storage = _CountingStorage()
        backend = B64Backend(poll_seconds=0.08)
        batch = ParallelImageOrchestrator(
            backend,
            storage,
            max_parallel_images=4,
            max_retries=0,
        ).render(_scenes(4))
        assert storage.uploads == 4
        assert all(info.url for info in batch.images)
        assert all(t.upload_ms > 0 for t in batch.timings)


class TestImageReportSection:
    def test_format_image_generation_block(self) -> None:
        text = format_image_generation_report(
            [
                ImageJobTiming(scene_id=1, total_ms=74_000),
                ImageJobTiming(scene_id=2, total_ms=69_000),
                ImageJobTiming(scene_id=3, total_ms=71_000),
                ImageJobTiming(scene_id=4, total_ms=73_000),
            ],
            total_parallel_ms=75_000,
        )
        assert "Image Generation" in text
        assert "Scene 1   74s" in text
        assert "Scene 2   69s" in text
        assert "Total Parallel Time: 75s" in text

    def test_pipeline_report_includes_image_section(self) -> None:
        report = PipelineReport(
            total_runtime_ms=120_000,
            total_llm_cost=0.01,
            image_parallel_ms=75_000,
            image_timings=[
                {"scene_id": 1, "total_ms": 74000, "success": True},
                {"scene_id": 2, "total_ms": 69000, "success": True},
            ],
        )
        text = format_pipeline_report(report)
        assert "Image Generation" in text
        assert "Scene 1   74s" in text
        assert "Total Parallel Time: 75s" in text
