"""Optional RunPod-shaped audio provider placeholder (disabled by default)."""

from __future__ import annotations

from typing import Any

from src.audio.exceptions import AudioProviderError
from src.audio.models import AudioGenerationParams, AudioRequest, AudioResult
from src.media.base import MediaKind


class RunPodAudioProvider:
    """Architecture placeholder for a future audio worker.

    Never hardcodes a commercial TTS vendor. Remains disabled until an
    endpoint is configured via environment variables in YAML.
    """

    def __init__(
        self,
        *,
        name: str = "runpod",
        enabled: bool = False,
        endpoint_id: str | None = None,
    ) -> None:
        self._name = name
        self._enabled = enabled
        self._endpoint_id = endpoint_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> MediaKind:
        return MediaKind.VOICE

    def healthcheck(self) -> dict[str, Any]:
        return {
            "provider": self._name,
            "kind": self.kind.value,
            "ready": False,
            "live": False,
            "enabled": self._enabled,
            "endpoint_configured": bool(self._endpoint_id),
            "message": "Audio worker not attached — use stub provider",
        }

    def generate(
        self,
        request: AudioRequest,
        params: AudioGenerationParams,
    ) -> AudioResult:
        raise AudioProviderError(
            "RunPod audio provider is an architecture stub. "
            "Enable a concrete worker or use provider type 'stub'."
        )
