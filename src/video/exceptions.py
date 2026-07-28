"""Exceptions for the provider-agnostic video engine."""

from __future__ import annotations


class VideoError(Exception):
    """Base error for the video engine."""


class VideoConfigError(VideoError):
    """Raised when video router YAML / registry config is invalid."""


class VideoRoutingError(VideoError):
    """Raised when a quality mode / model / provider cannot be resolved."""


class VideoProviderError(VideoError):
    """Raised when a provider fails to generate a video."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
