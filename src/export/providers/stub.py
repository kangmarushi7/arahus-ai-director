"""Shared stub publish behavior for all platforms (no OAuth / no network)."""

from __future__ import annotations

import hashlib
from typing import Any

from src.export.models import (
    PublishJob,
    PublishPlatform,
    PublishResult,
    PublishStatus,
    ProjectPackageManifest,
)


class StubPublishProvider:
    """Deterministic fake publisher used for architecture + tests."""

    def __init__(
        self,
        *,
        platform: PublishPlatform,
        name: str | None = None,
        enabled: bool = True,
    ) -> None:
        self._platform = platform
        self._name = name or platform.value
        self._enabled = enabled

    @property
    def name(self) -> str:
        return self._name

    @property
    def platform(self) -> str:
        return self._platform.value

    def healthcheck(self) -> dict[str, Any]:
        return {
            "provider": self._name,
            "platform": self._platform.value,
            "ready": self._enabled,
            "live": False,
            "oauth": False,
            "message": "Stub publisher — OAuth not implemented in Sprint 6.6",
        }

    def publish(
        self,
        job: PublishJob,
        *,
        package: ProjectPackageManifest | None = None,
        package_path: str | None = None,
    ) -> PublishResult:
        seed = hashlib.sha1(
            f"{self._platform.value}:{job.project_id}:{job.id}".encode()
        ).hexdigest()[:10]
        external_id = f"{self._platform.value}_{seed}"
        if job.schedule_at:
            status = PublishStatus.SCHEDULED
            message = f"Scheduled on {self._platform.value} for {job.schedule_at}"
            url = None
        else:
            status = PublishStatus.PUBLISHED
            message = f"Stub-published to {self._platform.value}"
            url = f"https://publish.stub.arahus.local/{self._platform.value}/{external_id}"
        return PublishResult(
            platform=self._platform,
            provider=self._name,
            status=status,
            external_id=external_id,
            external_url=url,
            message=message,
            live=False,
            metadata={
                "stub": True,
                "oauth": False,
                "package_path": package_path,
                "package_files": package.files if package else [],
                "title": job.title,
            },
        )


def youtube_provider() -> StubPublishProvider:
    return StubPublishProvider(platform=PublishPlatform.YOUTUBE, name="youtube")


def instagram_provider() -> StubPublishProvider:
    return StubPublishProvider(platform=PublishPlatform.INSTAGRAM, name="instagram")


def tiktok_provider() -> StubPublishProvider:
    return StubPublishProvider(platform=PublishPlatform.TIKTOK, name="tiktok")


def x_provider() -> StubPublishProvider:
    return StubPublishProvider(platform=PublishPlatform.X, name="x")
