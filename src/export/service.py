"""Export & Publishing Studio orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.audio.service import AudioStudioService
from src.audio.subtitles import export_subtitles
from src.export.models import (
    ExportFormat,
    ExportPresetId,
    ExportStudioState,
    PublishJob,
    PublishPlatform,
    PublishStatus,
    RenderJob,
    RenderJobStatus,
    _utc_iso,
)
from src.export.presets import list_presets, settings_from_preset
from src.export.providers import build_publish_provider
from src.export.queue import RenderQueue
from src.export.store import ExportStore
from src.timeline.service import TimelineService


class ExportStudioService:
    """High-level Export / Publish API.

    Publishing goes through abstract providers only — no OAuth in Sprint 6.6.
    """

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        store: ExportStore | None = None,
        timeline_service: TimelineService | None = None,
        audio_service: AudioStudioService | None = None,
        project_loader: Callable[[str], dict[str, Any]] | None = None,
        storyboard_loader: Callable[[str], dict[str, Any] | None] | None = None,
        memory_loader: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        root_path = Path(root) if root is not None else Path("artifacts") / "projects"
        self._store = store or ExportStore(root=root_path)
        self._queue = RenderQueue(self._store)
        self._timelines = timeline_service
        self._audio = audio_service
        self._project_loader = project_loader
        self._storyboard_loader = storyboard_loader
        self._memory_loader = memory_loader

    @property
    def store(self) -> ExportStore:
        return self._store

    def load(self, project_id: str) -> ExportStudioState | None:
        return self._store.load(project_id)

    def get_or_create(self, project_id: str) -> ExportStudioState:
        existing = self.load(project_id)
        if existing is not None:
            return existing
        state = ExportStudioState(project_id=project_id)
        self._store.save(state)
        return state

    def save(self, state: ExportStudioState) -> ExportStudioState:
        board = state.touch()
        self._store.save(board)
        return board

    def presets(self) -> list[dict[str, Any]]:
        return [p.model_dump(mode="json") for p in list_presets()]

    def provider_health(self) -> list[dict[str, Any]]:
        return [
            build_publish_provider(platform.value).healthcheck()
            for platform in PublishPlatform
        ]

    def enqueue(
        self,
        project_id: str,
        *,
        preset: ExportPresetId | str = ExportPresetId.YOUTUBE,
        format: ExportFormat | str | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        aspect: str | None = None,
        include_subtitles: bool = True,
        include_audio: bool = True,
        custom_label: str | None = None,
        process: bool = True,
    ) -> ExportStudioState:
        preset_id = (
            preset
            if isinstance(preset, ExportPresetId)
            else ExportPresetId(preset)
        )
        fmt = None
        if format is not None:
            fmt = format if isinstance(format, ExportFormat) else ExportFormat(format)
        settings = settings_from_preset(
            preset_id,
            format=fmt,
            width=width,
            height=height,
            fps=fps,
            aspect=aspect,
            include_subtitles=include_subtitles,
            include_audio=include_audio,
            custom_label=custom_label,
        )
        state = self.get_or_create(project_id)
        job = RenderJob(project_id=project_id, settings=settings)
        state = self._queue.enqueue(state, job)
        self._store.save(state)
        if process:
            state = self.process_queue(project_id)
        return state

    def process_queue(self, project_id: str) -> ExportStudioState:
        state = self.get_or_create(project_id)
        return self._queue.drain(
            state,
            context_loader=lambda job: self._package_context(job),
        )

    def cancel(self, project_id: str, job_id: str) -> ExportStudioState:
        state = self.get_or_create(project_id)
        state = self._queue.cancel(state, job_id)
        self._store.save(state)
        return state

    def pause(self, project_id: str, job_id: str) -> ExportStudioState:
        state = self.get_or_create(project_id)
        state = self._queue.pause(state, job_id)
        self._store.save(state)
        return state

    def resume(
        self, project_id: str, job_id: str, *, process: bool = True
    ) -> ExportStudioState:
        state = self.get_or_create(project_id)
        state = self._queue.resume(state, job_id)
        self._store.save(state)
        if process:
            state = self.process_queue(project_id)
        return state

    def retry(
        self, project_id: str, job_id: str, *, process: bool = True
    ) -> ExportStudioState:
        state = self.get_or_create(project_id)
        state = self._queue.retry(state, job_id)
        self._store.save(state)
        if process:
            state = self.process_queue(project_id)
        return state

    def schedule_publish(
        self,
        project_id: str,
        *,
        render_job_id: str,
        platform: PublishPlatform | str,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        schedule_at: str | None = None,
        run: bool = True,
    ) -> ExportStudioState:
        platform_id = (
            platform
            if isinstance(platform, PublishPlatform)
            else PublishPlatform(platform)
        )
        state = self.get_or_create(project_id)
        render = state.job_by_id(render_job_id)
        if render.status != RenderJobStatus.READY:
            raise ValueError("Render job must be ready before publishing")

        job = PublishJob(
            project_id=project_id,
            render_job_id=render_job_id,
            platform=platform_id,
            status=PublishStatus.DRAFT if not run else PublishStatus.DRAFT,
            title=title or f"{platform_id.value} export",
            description=description,
            tags=tags or [],
            schedule_at=schedule_at,
            provider=platform_id.value,
        )
        publishes = list(state.publishes)
        publishes.append(job)
        state = state.model_copy(update={"publishes": publishes}).touch()
        self._store.save(state)
        if run:
            state = self.run_publish(project_id, job.id)
        return state

    def run_publish(self, project_id: str, publish_id: str) -> ExportStudioState:
        state = self.get_or_create(project_id)
        job = state.publish_by_id(publish_id)
        if job.status in (PublishStatus.PUBLISHED, PublishStatus.CANCELLED):
            raise ValueError(f"Cannot run publish in status {job.status.value}")

        render = state.job_by_id(job.render_job_id)
        provider = build_publish_provider(job.platform.value)
        publishing = job.touch(status=PublishStatus.PUBLISHING, error=None)
        state = self._replace_publish(state, publishing)

        result = provider.publish(
            publishing,
            package_path=render.package_path,
            package=None,
        )
        finished = publishing.touch(
            status=result.status,
            external_id=result.external_id,
            external_url=result.external_url,
            published_at=_utc_iso()
            if result.status == PublishStatus.PUBLISHED
            else None,
            provider=result.provider,
            error=None if result.status != PublishStatus.FAILED else result.message,
        )
        state = self._replace_publish(state, finished)

        # Mirror publish status onto matching history entry
        history = []
        for entry in state.history:
            if entry.render_job_id == job.render_job_id:
                history.append(
                    entry.model_copy(
                        update={
                            "publish_status": finished.status,
                            "publish_platform": finished.platform,
                            "publish_url": finished.external_url,
                        }
                    )
                )
            else:
                history.append(entry)
        state = state.model_copy(update={"history": history}).touch()
        self._store.save(state)
        return state

    def cancel_publish(self, project_id: str, publish_id: str) -> ExportStudioState:
        state = self.get_or_create(project_id)
        job = state.publish_by_id(publish_id)
        if job.status in (PublishStatus.PUBLISHED, PublishStatus.CANCELLED):
            raise ValueError(f"Cannot cancel publish in status {job.status.value}")
        updated = job.touch(status=PublishStatus.CANCELLED)
        state = self._replace_publish(state, updated)
        self._store.save(state)
        return state

    def _replace_publish(
        self, state: ExportStudioState, job: PublishJob
    ) -> ExportStudioState:
        publishes = [
            job if item.id == job.id else item for item in state.publishes
        ]
        return state.model_copy(update={"publishes": publishes}).touch()

    def _package_context(self, job: RenderJob) -> dict[str, Any]:
        project_id = job.project_id
        project: dict[str, Any] = {"id": project_id}
        if self._project_loader:
            project = self._project_loader(project_id) or project
        storyboard = (
            self._storyboard_loader(project_id) if self._storyboard_loader else None
        )
        memory = self._memory_loader(project_id) if self._memory_loader else None
        timeline = None
        if self._timelines is not None:
            doc = self._timelines.load(project_id)
            timeline = doc.to_dict() if doc else None
        audio_payload = None
        subtitles_srt = None
        subtitles_vtt = None
        if self._audio is not None and job.settings.include_subtitles:
            audio_doc = self._audio.load(project_id)
            if audio_doc is not None:
                audio_payload = audio_doc.to_dict()
                if audio_doc.subtitles:
                    from src.audio.models import SubtitleFormat

                    subtitles_srt = export_subtitles(
                        audio_doc.subtitles, SubtitleFormat.SRT
                    )
                    subtitles_vtt = export_subtitles(
                        audio_doc.subtitles, SubtitleFormat.VTT
                    )
        elif self._audio is not None:
            audio_doc = self._audio.load(project_id)
            if audio_doc is not None:
                audio_payload = audio_doc.to_dict()
        return {
            "project": project,
            "storyboard": storyboard,
            "timeline": timeline,
            "memory": memory,
            "audio": audio_payload,
            "subtitles_srt": subtitles_srt,
            "subtitles_vtt": subtitles_vtt,
        }
