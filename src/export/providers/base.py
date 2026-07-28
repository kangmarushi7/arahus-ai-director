"""Publishing provider protocol — no OAuth in this sprint."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.export.models import PublishJob, PublishResult, ProjectPackageManifest


@runtime_checkable
class PublishProvider(Protocol):
    """Provider-agnostic social publish interface.

    Call sites must never import platform SDKs. Routers select adapters by
    YAML / type string only. OAuth is intentionally out of scope for Sprint 6.6.
    """

    @property
    def name(self) -> str:
        """Stable provider id (e.g. ``youtube``, ``stub``)."""

    @property
    def platform(self) -> str:
        """Platform key matching :class:`~src.export.models.PublishPlatform`."""

    def healthcheck(self) -> dict[str, Any]:
        """Readiness — typically ``live: False`` until OAuth is wired."""

    def publish(
        self,
        job: PublishJob,
        *,
        package: ProjectPackageManifest | None = None,
        package_path: str | None = None,
    ) -> PublishResult:
        """Publish or schedule content. Stub implementations do not hit networks."""
