"""Audio engine exceptions."""

from __future__ import annotations


class AudioError(Exception):
    """Base audio engine error."""


class AudioConfigError(AudioError):
    """Invalid audio router YAML / configuration."""


class AudioRoutingError(AudioError):
    """Could not resolve a provider / model for a request."""


class AudioProviderError(AudioError):
    """Provider refused or failed a generation request."""
