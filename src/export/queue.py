"""In-process render queue — progress, cancel, retry, resume (stub engine)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.export.engine import render_stub_output
from src.export.models import (
    ExportHistoryEntry,
    ExportStudioState,
    RenderJob,
    RenderJobStatus,
    _utc_iso,
)
from src.export.package import build_project_package
from src.export.store import ExportStore

logger = logging.getLogger(__name__)

PackageContext = dict[str, Any]


class RenderQueue:
    """Advance queued jobs through a stub encoder + project package builder.

    Designed for architecture / Studio UX. Real ffmpeg workers can replace
    :func:`render_stub_output` later without changing the queue API.
    """

    def __init__(self, store: ExportStore) -> None:
        self._store = store

    def enqueue(self, state: ExportStudioState, job: RenderJob) -> ExportStudioState:
        queue = list(state.queue)
        queue.append(job)
        return state.model_copy(update={"queue": queue}).touch()

    def replace_job(
        self, state: ExportStudioState, job: RenderJob
    ) -> ExportStudioState:
        queue = [job if item.id == job.id else item for item in state.queue]
        return state.model_copy(update={"queue": queue}).touch()

    def cancel(self, state: ExportStudioState, job_id: str) -> ExportStudioState:
        job = state.job_by_id(job_id)
        if job.status in (RenderJobStatus.READY, RenderJobStatus.CANCELLED):
            raise ValueError(f"Cannot cancel job in status {job.status.value}")
        updated = job.touch(
            status=RenderJobStatus.CANCELLED,
            message="Cancelled",
            progress=job.progress,
            finished_at=_utc_iso(),
            resumable=False,
        )
        return self.replace_job(state, updated)

    def pause(self, state: ExportStudioState, job_id: str) -> ExportStudioState:
        job = state.job_by_id(job_id)
        if job.status not in (
            RenderJobStatus.QUEUED,
            RenderJobStatus.PROCESSING,
        ):
            raise ValueError(f"Cannot pause job in status {job.status.value}")
        updated = job.touch(
            status=RenderJobStatus.PAUSED,
            message="Paused — resume to continue",
            checkpoint={
                **job.checkpoint,
                "progress": job.progress,
                "paused_at": _utc_iso(),
            },
            resumable=True,
        )
        return self.replace_job(state, updated)

    def resume(self, state: ExportStudioState, job_id: str) -> ExportStudioState:
        job = state.job_by_id(job_id)
        if job.status not in (RenderJobStatus.PAUSED, RenderJobStatus.FAILED):
            raise ValueError(f"Cannot resume job in status {job.status.value}")
        if not job.resumable and job.status == RenderJobStatus.FAILED:
            raise ValueError("Job is not resumable")
        updated = job.touch(
            status=RenderJobStatus.QUEUED,
            message="Resumed — waiting in queue",
            error=None,
            finished_at=None,
        )
        return self.replace_job(state, updated)

    def retry(self, state: ExportStudioState, job_id: str) -> ExportStudioState:
        job = state.job_by_id(job_id)
        if job.status not in (
            RenderJobStatus.FAILED,
            RenderJobStatus.CANCELLED,
        ):
            raise ValueError(f"Cannot retry job in status {job.status.value}")
        if job.attempt >= job.max_attempts:
            raise ValueError("Max retry attempts exceeded")
        updated = job.touch(
            status=RenderJobStatus.QUEUED,
            message="Queued for retry",
            progress=0.0,
            error=None,
            output_path=None,
            package_path=None,
            finished_at=None,
            started_at=None,
            attempt=job.attempt + 1,
            resumable=True,
            checkpoint={},
        )
        return self.replace_job(state, updated)

    def process_next(
        self,
        state: ExportStudioState,
        *,
        context_loader: Callable[[RenderJob], PackageContext] | None = None,
    ) -> ExportStudioState:
        """Process the first queued (or resumable paused→queued) job to completion."""
        job = next(
            (item for item in state.queue if item.status == RenderJobStatus.QUEUED),
            None,
        )
        if job is None:
            return state

        started = job.touch(
            status=RenderJobStatus.PROCESSING,
            message="Encoding (stub)",
            progress=max(job.progress, 0.1),
            started_at=job.started_at or _utc_iso(),
            attempt=max(job.attempt, 1),
        )
        state = self.replace_job(state, started)
        self._store.save(state)

        try:
            # Mid-progress checkpoint (supports pause/resume UX)
            mid = started.touch(
                progress=0.55,
                message="Building package",
                checkpoint={"stage": "package", "progress": 0.55},
            )
            state = self.replace_job(state, mid)
            # Re-read in case cancel/pause raced (best-effort for in-process stub)
            current = state.job_by_id(mid.id)
            if current.status == RenderJobStatus.CANCELLED:
                return state
            if current.status == RenderJobStatus.PAUSED:
                return state

            job_dir = self._store.job_dir(state.project_id, mid.id)
            output = render_stub_output(mid, job_dir)

            package_path: str | None = None
            if context_loader is not None:
                ctx = context_loader(mid)
                package_dir = job_dir / "package"
                manifest = build_project_package(
                    job=mid,
                    dest=package_dir,
                    project=ctx.get("project") or {},
                    storyboard=ctx.get("storyboard"),
                    timeline=ctx.get("timeline"),
                    memory=ctx.get("memory"),
                    audio=ctx.get("audio"),
                    subtitles_srt=ctx.get("subtitles_srt"),
                    subtitles_vtt=ctx.get("subtitles_vtt"),
                )
                package_path = str(package_dir)
                (job_dir / "manifest.json").write_text(
                    manifest.model_dump_json(indent=2),
                    encoding="utf-8",
                )

            ready = mid.touch(
                status=RenderJobStatus.READY,
                progress=1.0,
                message="Ready",
                output_path=str(output),
                package_path=package_path,
                finished_at=_utc_iso(),
                checkpoint={"stage": "done", "progress": 1.0},
                error=None,
            )
            state = self.replace_job(state, ready)

            version = len(state.history) + 1
            entry = ExportHistoryEntry(
                project_id=state.project_id,
                version=version,
                render_job_id=ready.id,
                settings=ready.settings,
                output_path=ready.output_path,
                package_path=ready.package_path,
                message=f"v{version} {ready.settings.preset.value} {ready.settings.format.value}",
            )
            history = list(state.history)
            history.append(entry)
            state = state.model_copy(update={"history": history}).touch()
            self._store.save(state)
            logger.info(
                "event=export_ready project_id=%r job_id=%r path=%s",
                state.project_id,
                ready.id,
                ready.output_path,
            )
            return state
        except Exception as exc:  # noqa: BLE001
            failed = started.touch(
                status=RenderJobStatus.FAILED,
                message="Failed",
                error=str(exc),
                finished_at=_utc_iso(),
                resumable=True,
            )
            state = self.replace_job(state, failed)
            self._store.save(state)
            logger.warning(
                "event=export_failed project_id=%r job_id=%r error=%s",
                state.project_id,
                failed.id,
                exc,
            )
            return state

    def drain(
        self,
        state: ExportStudioState,
        *,
        context_loader: Callable[[RenderJob], PackageContext] | None = None,
        max_jobs: int = 32,
    ) -> ExportStudioState:
        """Process all queued jobs (used by API process endpoint)."""
        for _ in range(max_jobs):
            before = [j.id for j in state.queue if j.status == RenderJobStatus.QUEUED]
            if not before:
                break
            state = self.process_next(state, context_loader=context_loader)
        return state
