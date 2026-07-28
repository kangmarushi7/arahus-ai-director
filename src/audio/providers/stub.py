"""Stub voice/audio provider — always available, never calls a vendor."""

from __future__ import annotations

import hashlib
from typing import Any

from src.audio.exceptions import AudioProviderError
from src.audio.models import AudioGenerationParams, AudioMode, AudioRequest, AudioResult
from src.media.base import MediaKind


class StubVoiceProvider:
    """Deterministic placeholder audio for tests and offline Studio.

    Returns synthetic URLs derived from prompt hashes. Does not call
    ElevenLabs, OpenAI, Azure, or any other vendor.
    """

    def __init__(self, *, name: str = "stub", enabled: bool = True) -> None:
        self._name = name
        self._enabled = enabled

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
            "ready": self._enabled,
            "live": False,
            "message": "Stub provider — no external TTS vendor configured",
        }

    def generate(
        self,
        request: AudioRequest,
        params: AudioGenerationParams,
    ) -> AudioResult:
        if not self._enabled:
            raise AudioProviderError(
                f"Stub voice provider {self._name!r} is disabled"
            )
        seed = hashlib.sha1(
            f"{request.mode.value}:{request.text}:{request.language}".encode()
        ).hexdigest()[:12]
        duration = float(request.duration or max(1.5, len(request.text.split()) * 0.35))
        if request.mode == AudioMode.MUSIC:
            duration = float(request.duration or 30.0)
            slug = f"music-{request.mood.value if request.mood else 'ambient'}-{seed}"
        elif request.mode == AudioMode.SFX:
            duration = float(request.duration or 2.0)
            slug = f"sfx-{seed}"
        else:
            slug = f"voice-{seed}"

        return AudioResult(
            prompt=request.text or request.prompt or slug,
            url=f"https://audio.stub.arahus.local/{slug}.{params.format}",
            duration_seconds=round(duration, 2),
            format=params.format,
            sample_rate=params.sample_rate,
            provider=self._name,
            model_id=params.model_id,
            metadata={
                "stub": True,
                "mode": request.mode.value,
                "language": request.language,
                "emotion": request.emotion.value if request.emotion else None,
                "speech_rate": request.speech_rate,
                "pitch": request.pitch,
                "clone_ref": request.clone_ref,
            },
        )
