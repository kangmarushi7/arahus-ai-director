"""Voice / audio provider protocol — vendor-agnostic."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.audio.models import AudioGenerationParams, AudioRequest, AudioResult
from src.media.base import MediaKind, MediaProvider


@runtime_checkable
class VoiceProvider(MediaProvider, Protocol):
    """Provider-agnostic TTS / music / SFX interface.

    Call sites must never import concrete vendor SDKs. Routers select
    implementations solely by ``cfg.type`` strings from YAML.
    """

    @property
    def name(self) -> str:
        """Stable provider identifier (e.g. ``stub``, ``runpod``)."""

    @property
    def kind(self) -> MediaKind:
        """Typically :attr:`MediaKind.VOICE` or :attr:`MediaKind.AUDIO`."""

    def healthcheck(self) -> dict[str, Any]:
        """Return readiness metadata for Settings / OpenAPI."""

    def generate(
        self,
        request: AudioRequest,
        params: AudioGenerationParams,
    ) -> AudioResult:
        """Synthesize audio and return a URL / asset reference."""
