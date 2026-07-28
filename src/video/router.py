"""Task/quality-based video router — public generation entry point."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from src.media.request import GenerationProfileName, QualityMode
from src.media.router import MediaRouter
from src.models.image import VideoResult
from src.video.config import ProviderConfig, VideoRouterConfig, load_video_config
from src.video.exceptions import VideoConfigError, VideoProviderError, VideoRoutingError
from src.video.metrics import VideoMetrics
from src.video.models import (
    VideoGenerationMetrics,
    VideoGenerationResult,
    VideoRequest,
)
from src.video.providers.base import VideoProvider
from src.video.providers.runpod import RunPodVideoProvider
from src.video.registry import ModelRegistry

logger = logging.getLogger(__name__)


class VideoRouter(MediaRouter):
    """Route quality modes / profiles to configured video providers.

    Public entry point::

        result = router.generate(VideoRequest(prompt="...", profile="production"))
        # or
        result = router.generate("...", source_image=url, profile="cinematic")
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        providers: Mapping[str, VideoProvider] | None = None,
        metrics: VideoMetrics | None = None,
    ) -> None:
        self._registry = registry
        self._metrics = metrics or VideoMetrics()
        self._providers: dict[str, VideoProvider] = (
            dict(providers)
            if providers is not None
            else self._build_providers(registry.config)
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | None = None,
        *,
        metrics: VideoMetrics | None = None,
        providers: Mapping[str, VideoProvider] | None = None,
    ) -> VideoRouter:
        """Construct a router from packaged or custom YAML."""
        registry = ModelRegistry.from_yaml(path)
        return cls(registry, providers=providers, metrics=metrics)

    @classmethod
    def from_config(
        cls,
        config: VideoRouterConfig,
        *,
        metrics: VideoMetrics | None = None,
        providers: Mapping[str, VideoProvider] | None = None,
    ) -> VideoRouter:
        return cls(ModelRegistry(config), providers=providers, metrics=metrics)

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def config(self) -> VideoRouterConfig:
        return self._registry.config

    @property
    def metrics(self) -> VideoMetrics:
        return self._metrics

    @property
    def providers(self) -> Mapping[str, VideoProvider]:
        return self._providers

    def generate(
        self,
        request: VideoRequest | str,
        **kwargs: Any,
    ) -> VideoGenerationResult:
        """Generate a video — the only public entry point for the video engine.

        Accepts a :class:`VideoRequest` or a prompt string plus keyword overrides
        (``source_image``, ``duration``, ``profile``, …).
        """
        resolved = self._coerce_request(request, **kwargs)
        params = self._registry.resolve(resolved)

        try:
            backend = self._providers[params.provider]
        except KeyError as exc:
            raise VideoRoutingError(
                f"No video provider registered for {params.provider!r}"
            ) from exc

        started = time.perf_counter()
        logger.info(
            "event=video_request_start provider=%s model=%s quality=%s "
            "profile=%s mode=%s duration=%s resolution=%s",
            params.provider,
            params.model_id,
            params.quality,
            params.profile,
            params.mode,
            params.duration,
            params.resolution,
        )
        try:
            video = backend.generate(resolved, params)
        except VideoProviderError as exc:
            runtime_ms = (time.perf_counter() - started) * 1000.0
            failure = self._failure_metrics(params, runtime_ms, str(exc))
            self._metrics.record(failure)
            logger.error(
                "event=video_request_failed provider=%s model=%s error=%s",
                params.provider,
                params.model_id,
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            runtime_ms = (time.perf_counter() - started) * 1000.0
            wrapped = VideoProviderError(
                str(exc),
                provider=params.provider,
                model=params.model_id,
            )
            self._metrics.record(self._failure_metrics(params, runtime_ms, str(exc)))
            raise wrapped from exc

        if not isinstance(video, VideoResult):
            raise VideoProviderError(
                f"Provider {params.provider!r} returned {type(video).__name__}, "
                "expected VideoResult",
                provider=params.provider,
                model=params.model_id,
            )

        runtime_ms = (time.perf_counter() - started) * 1000.0
        gpu_seconds = round(runtime_ms / 1000.0, 3)
        # Prefer provider-reported duration when present.
        duration = (
            float(video.duration_seconds)
            if video.duration_seconds is not None
            else params.duration
        )
        metrics = VideoGenerationMetrics(
            provider=params.provider,
            model=params.model_id,
            runtime_ms=round(runtime_ms, 3),
            gpu_seconds=gpu_seconds,
            estimated_cost=params.estimated_cost,
            resolution=params.resolution,
            quality=params.quality,
            profile=params.profile,
            success=True,
            duration=duration,
            fps=int(video.fps or params.fps),
            mode=params.mode,
        )
        self._metrics.record(metrics)
        logger.info(
            "event=video_request_complete provider=%s model=%s "
            "runtime_ms=%.1f gpu_seconds=%.3f cost=%.6f resolution=%s duration=%s",
            metrics.provider,
            metrics.model,
            metrics.runtime_ms,
            metrics.gpu_seconds,
            metrics.estimated_cost,
            metrics.resolution,
            metrics.duration,
        )

        # Fill missing result fields from resolved params.
        filled = video.model_copy(
            update={
                "prompt": video.prompt or resolved.prompt,
                "duration_seconds": video.duration_seconds
                if video.duration_seconds is not None
                else params.duration,
                "fps": video.fps if video.fps is not None else params.fps,
                "width": video.width if video.width is not None else params.width,
                "height": video.height if video.height is not None else params.height,
                "source_image": video.source_image or resolved.source_image,
                "source_image_urls": video.source_image_urls
                or list(resolved.source_image_urls),
                "seed": video.seed if video.seed is not None else resolved.seed,
            }
        )
        return VideoGenerationResult(
            prompt=resolved.prompt,
            video=filled,
            params=params,
            metrics=metrics,
            request_mode=resolved.mode,
        )

    @staticmethod
    def _coerce_request(
        request: VideoRequest | str,
        **kwargs: Any,
    ) -> VideoRequest:
        if isinstance(request, VideoRequest):
            if not kwargs:
                return request
            return request.model_copy(update=kwargs)
        if not isinstance(request, str):
            raise TypeError("request must be a VideoRequest or prompt string")
        return VideoRequest(prompt=request, **kwargs)

    @staticmethod
    def _failure_metrics(
        params: Any,
        runtime_ms: float,
        error: str,
    ) -> VideoGenerationMetrics:
        return VideoGenerationMetrics(
            provider=params.provider,
            model=params.model_id,
            runtime_ms=round(runtime_ms, 3),
            gpu_seconds=round(runtime_ms / 1000.0, 3),
            estimated_cost=0.0,
            resolution=params.resolution,
            quality=params.quality,
            profile=params.profile,
            success=False,
            error=error,
            duration=float(params.duration),
            fps=int(params.fps),
            mode=params.mode,
        )

    @staticmethod
    def _build_providers(config: VideoRouterConfig) -> dict[str, VideoProvider]:
        providers: dict[str, VideoProvider] = {}
        for name, provider_cfg in config.providers.items():
            providers[name] = _build_provider(provider_cfg)
        return providers


def _build_provider(cfg: ProviderConfig) -> VideoProvider:
    import os

    if cfg.type != "runpod":
        raise VideoConfigError(f"Unsupported video provider type {cfg.type!r}")

    api_key = os.getenv(cfg.api_key_env, "").strip()
    endpoint = os.getenv(cfg.endpoint_id_env, "").strip() or None
    poll_timeout = max(60.0, float(cfg.timeout_seconds) * 2.0)
    return RunPodVideoProvider(
        name=cfg.name,
        enabled=cfg.enabled,
        endpoint_id=endpoint,
        api_key=api_key or None,
        base_url=cfg.base_url,
        timeout_seconds=cfg.timeout_seconds,
        poll_timeout_seconds=poll_timeout,
    )


class VideoEngineAdapter:
    """Adapt :class:`VideoRouter` for future pipeline integration.

    Does not change the public :meth:`DirectorPipeline.generate` API. Callers
    that want video can use this adapter once a live provider is injected.
    """

    def __init__(
        self,
        router: VideoRouter,
        *,
        quality: QualityMode = "production",
        profile: GenerationProfileName | None = None,
    ) -> None:
        self._router = router
        self._quality = quality
        self._profile = profile

    @property
    def router(self) -> VideoRouter:
        return self._router

    def generate(
        self,
        prompt: str,
        *,
        source_image: str | None = None,
        source_image_urls: list[str] | None = None,
        **kwargs: Any,
    ) -> VideoResult:
        """Convenience generate → pipeline :class:`~src.models.image.VideoResult`."""
        result = self._router.generate(
            prompt,
            quality=kwargs.pop("quality", self._quality),
            profile=kwargs.pop("profile", self._profile),
            source_image=source_image,
            source_image_urls=source_image_urls or [],
            **kwargs,
        )
        return result.to_video_result()


@lru_cache(maxsize=1)
def get_video_router() -> VideoRouter:
    """Return a process-wide :class:`VideoRouter` singleton."""
    return VideoRouter.from_yaml()


def reset_video_router_singleton() -> None:
    """Clear the cached router (tests)."""
    get_video_router.cache_clear()
