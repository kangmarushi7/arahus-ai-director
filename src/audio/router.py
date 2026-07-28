"""Audio router — sole public generation entry for voice / music / SFX."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from src.audio.config import AudioRouterConfig, ProviderConfig, load_audio_config
from src.audio.exceptions import AudioProviderError, AudioRoutingError
from src.audio.models import (
    AudioGenerationParams,
    AudioMode,
    AudioRequest,
    AudioResult,
)
from src.audio.providers.base import VoiceProvider
from src.audio.providers.runpod import RunPodAudioProvider
from src.audio.providers.stub import StubVoiceProvider
from src.media.request import GenerationProfileName, QualityMode
from src.media.router import MediaRouter

logger = logging.getLogger(__name__)


def _build_provider(name: str, cfg: ProviderConfig) -> VoiceProvider:
    """Instantiate a provider by YAML ``type`` only — no vendor imports at call sites."""
    kind = cfg.type.strip().casefold()
    if kind == "stub":
        return StubVoiceProvider(name=name, enabled=cfg.enabled)
    if kind == "runpod":
        endpoint = None
        if cfg.endpoint_id_env:
            endpoint = os.environ.get(cfg.endpoint_id_env)
        return RunPodAudioProvider(
            name=name,
            enabled=cfg.enabled,
            endpoint_id=endpoint,
        )
    raise AudioRoutingError(
        f"Unknown audio provider type {cfg.type!r}. "
        "Register adapters by type string only (stub, runpod, …)."
    )


class AudioRouter(MediaRouter):
    """Route audio generation to configured providers without vendor lock-in."""

    def __init__(
        self,
        config: AudioRouterConfig,
        *,
        providers: Mapping[str, VoiceProvider] | None = None,
    ) -> None:
        self._config = config
        self._providers: dict[str, VoiceProvider] = (
            dict(providers)
            if providers is not None
            else {
                name: _build_provider(name, cfg)
                for name, cfg in config.providers.items()
            }
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | None = None,
        *,
        providers: Mapping[str, VoiceProvider] | None = None,
    ) -> AudioRouter:
        return cls(load_audio_config(path), providers=providers)

    @property
    def config(self) -> AudioRouterConfig:
        return self._config

    @property
    def providers(self) -> Mapping[str, VoiceProvider]:
        return self._providers

    def resolve(self, request: AudioRequest) -> AudioGenerationParams:
        quality: QualityMode = request.quality or self._config.default_quality  # type: ignore[assignment]
        if quality not in ("preview", "production", "experimental"):
            quality = "production"
        qm = self._config.quality_modes.get(quality)
        model_key = qm.model if qm else next(iter(self._config.models), "voice-placeholder")

        for key, model in self._config.models.items():
            if request.mode.value in model.modes:
                model_key = key
                break

        model = self._config.models.get(model_key)
        if model is None:
            raise AudioRoutingError(f"Unknown audio model {model_key!r}")
        provider = model.provider or self._config.default_provider
        profile: GenerationProfileName = request.profile or "production"  # type: ignore[assignment]
        if profile not in ("preview", "production", "cinematic"):
            profile = "production"
        return AudioGenerationParams(
            model_key=model_key,
            model_id=model.model_id,
            provider=provider,
            quality=quality,
            profile=profile,
            mode=request.mode,
            sample_rate=model.sample_rate,
            format=model.format,
            cost_per_second=model.cost_per_second,
        )

    def generate(
        self,
        request: AudioRequest | str,
        **kwargs: Any,
    ) -> AudioResult:
        if isinstance(request, str):
            mode = kwargs.pop("mode", AudioMode.TTS)
            if isinstance(mode, str):
                mode = AudioMode(mode)
            request = AudioRequest(prompt=request, text=request, mode=mode, **kwargs)
        elif not request.prompt and request.text:
            request = request.model_copy(update={"prompt": request.text})
        params = self.resolve(request)
        try:
            backend = self._providers[params.provider]
        except KeyError as exc:
            raise AudioRoutingError(
                f"No audio provider registered for {params.provider!r}"
            ) from exc
        logger.info(
            "event=audio_request_start provider=%s model=%s mode=%s language=%s",
            params.provider,
            params.model_id,
            request.mode.value,
            request.language,
        )
        try:
            result = backend.generate(request, params)
        except AudioProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AudioProviderError(str(exc)) from exc
        return result


@lru_cache(maxsize=1)
def get_audio_router() -> AudioRouter:
    return AudioRouter.from_yaml()


def reset_audio_router_singleton() -> None:
    get_audio_router.cache_clear()
