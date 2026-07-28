"""Export / publishing domain models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import StrictModel


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class ExportFormat(str, Enum):
    MP4 = "mp4"
    MOV = "mov"
    GIF = "gif"
    IMAGE_SEQUENCE = "image_sequence"


class ExportPresetId(str, Enum):
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM_REELS = "instagram_reels"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    X = "x"
    CUSTOM = "custom"


class RenderJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class PublishPlatform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    X = "x"


class PublishStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportPreset(StrictModel):
    id: ExportPresetId
    label: str
    aspect: str = "16:9"
    width: int = Field(default=1920, ge=16)
    height: int = Field(default=1080, ge=16)
    fps: int = Field(default=30, ge=1)
    max_duration_seconds: float | None = Field(default=None, ge=0.1)
    format: ExportFormat = ExportFormat.MP4
    description: str = ""


class ExportSettings(StrictModel):
    preset: ExportPresetId = ExportPresetId.YOUTUBE
    format: ExportFormat = ExportFormat.MP4
    aspect: str = "16:9"
    width: int = Field(default=1920, ge=16)
    height: int = Field(default=1080, ge=16)
    fps: int = Field(default=30, ge=1)
    include_subtitles: bool = True
    include_audio: bool = True
    custom_label: str | None = None


class RenderJob(StrictModel):
    """Background export / render job (architecture stub — no live encode)."""

    id: str = Field(default_factory=lambda: _new_id("render"))
    project_id: str
    settings: ExportSettings = Field(default_factory=ExportSettings)
    status: RenderJobStatus = RenderJobStatus.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = "Queued"
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)
    started_at: str | None = None
    finished_at: str | None = None
    output_path: str | None = None
    package_path: str | None = None
    error: str | None = None
    resumable: bool = True
    checkpoint: dict[str, Any] = Field(default_factory=dict)

    def touch(self, **updates: Any) -> RenderJob:
        payload = {"updated_at": _utc_iso(), **updates}
        return self.model_copy(update=payload)


class PublishJob(StrictModel):
    """Scheduled or immediate publish request — no OAuth in this sprint."""

    id: str = Field(default_factory=lambda: _new_id("publish"))
    project_id: str
    render_job_id: str
    platform: PublishPlatform
    status: PublishStatus = PublishStatus.DRAFT
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    schedule_at: str | None = None  # ISO-8601; None = publish now when run
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)
    published_at: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    error: str | None = None
    provider: str = "stub"

    def touch(self, **updates: Any) -> PublishJob:
        return self.model_copy(update={"updated_at": _utc_iso(), **updates})


class ExportHistoryEntry(StrictModel):
    """Immutable-ish history row for Studio Export page."""

    id: str = Field(default_factory=lambda: _new_id("hist"))
    project_id: str
    version: int = Field(default=1, ge=1)
    render_job_id: str
    settings: ExportSettings
    output_path: str | None = None
    package_path: str | None = None
    publish_status: PublishStatus | None = None
    publish_platform: PublishPlatform | None = None
    publish_url: str | None = None
    created_at: str = Field(default_factory=_utc_iso)
    message: str = ""


class ProjectPackageManifest(StrictModel):
    """Contents of an exported project package folder."""

    project_id: str
    render_job_id: str
    created_at: str = Field(default_factory=_utc_iso)
    files: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExportStudioState(StrictModel):
    """Persisted export studio document per project."""

    project_id: str
    version: int = Field(default=1, ge=1)
    queue: list[RenderJob] = Field(default_factory=list)
    publishes: list[PublishJob] = Field(default_factory=list)
    history: list[ExportHistoryEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)

    def touch(self) -> ExportStudioState:
        return self.model_copy(
            update={"updated_at": _utc_iso(), "version": self.version + 1}
        )

    def job_by_id(self, job_id: str) -> RenderJob:
        for job in self.queue:
            if job.id == job_id:
                return job
        raise KeyError(f"Render job {job_id!r} not found")

    def publish_by_id(self, publish_id: str) -> PublishJob:
        for job in self.publishes:
            if job.id == publish_id:
                return job
        raise KeyError(f"Publish job {publish_id!r} not found")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExportStudioState:
        return cls.model_validate(data)


class PublishResult(StrictModel):
    platform: PublishPlatform
    provider: str
    status: PublishStatus
    external_id: str | None = None
    external_url: str | None = None
    message: str = ""
    live: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
