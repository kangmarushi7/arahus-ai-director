"""Platform adapter modules — type-selected stubs, no OAuth."""

from __future__ import annotations

from src.export.models import PublishPlatform
from src.export.providers.base import PublishProvider
from src.export.providers.stub import (
    StubPublishProvider,
    instagram_provider,
    tiktok_provider,
    x_provider,
    youtube_provider,
)

__all__ = [
    "PublishProvider",
    "StubPublishProvider",
    "youtube_provider",
    "instagram_provider",
    "tiktok_provider",
    "x_provider",
    "build_publish_provider",
]


def build_publish_provider(platform: str) -> PublishProvider:
    """Factory by platform string — never imports OAuth SDKs."""
    key = platform.strip().casefold()
    mapping = {
        "youtube": youtube_provider,
        "instagram": instagram_provider,
        "tiktok": tiktok_provider,
        "x": x_provider,
        "twitter": x_provider,
        "stub": lambda: StubPublishProvider(
            platform=PublishPlatform.YOUTUBE,
            name="stub",
        ),
    }
    try:
        return mapping[key]()
    except KeyError as exc:
        raise ValueError(f"Unknown publish platform {platform!r}") from exc
