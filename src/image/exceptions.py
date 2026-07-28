"""Exceptions for the provider-agnostic image engine."""

from __future__ import annotations


class ImageError(Exception):
    """Base error for the image engine."""


class ImageConfigError(ImageError):
    """Raised when image router YAML / registry config is invalid."""


class ImageRoutingError(ImageError):
    """Raised when a quality mode / model / provider cannot be resolved."""


class ImageProviderError(ImageError):
    """Raised when a provider fails to generate an image."""

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
