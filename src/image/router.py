"""Task/quality-based image router — public generation entry point."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from src.image.config import ImageRouterConfig, ProviderConfig, load_image_config
from src.image.exceptions import ImageConfigError, ImageProviderError, ImageRoutingError
from src.image.metrics import ImageMetrics
from src.image.models import (
    GenerationProfileName,
    ImageGenerationMetrics,
    ImageGenerationResult,
    ImageRequest,
    QualityMode,
)
from src.image.providers.base import ImageProvider
from src.image.providers.runpod import RunPodImageProvider
from src.image.registry import ModelRegistry

logger = logging.getLogger(__name__)


class ImageRouter:
    """Route quality modes / profiles to configured image providers.

    Public entry point::

        result = router.generate(prompt="...", quality="production")
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        providers: Mapping[str, ImageProvider] | None = None,
        metrics: ImageMetrics | None = None,
        storage_client: Any | None = None,
    ) -> None:
        self._registry = registry
        self._metrics = metrics or ImageMetrics()
        self._storage = storage_client
        self._providers: dict[str, ImageProvider] = (
            dict(providers)
            if providers is not None
            else self._build_providers(registry.config, storage_client)
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | None = None,
        *,
        metrics: ImageMetrics | None = None,
        storage_client: Any | None = None,
        providers: Mapping[str, ImageProvider] | None = None,
    ) -> ImageRouter:
        """Construct a router from packaged or custom YAML."""
        registry = ModelRegistry.from_yaml(path)
        return cls(
            registry,
            providers=providers,
            metrics=metrics,
            storage_client=storage_client,
        )

    @classmethod
    def from_config(
        cls,
        config: ImageRouterConfig,
        *,
        metrics: ImageMetrics | None = None,
        storage_client: Any | None = None,
        providers: Mapping[str, ImageProvider] | None = None,
    ) -> ImageRouter:
        return cls(
            ModelRegistry(config),
            providers=providers,
            metrics=metrics,
            storage_client=storage_client,
        )

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def config(self) -> ImageRouterConfig:
        return self._registry.config

    @property
    def metrics(self) -> ImageMetrics:
        return self._metrics

    @property
    def providers(self) -> Mapping[str, ImageProvider]:
        return self._providers

    def generate(
        self,
        prompt: str,
        *,
        quality: QualityMode = "production",
        profile: GenerationProfileName | None = None,
        model: str | None = None,
        provider: str | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
        negative_prompt: str | None = None,
    ) -> ImageGenerationResult:
        """Generate an image — the only public entry point for the image engine.

        Resolves quality → model → profile, selects a provider, records metrics,
        and returns a structured :class:`ImageGenerationResult`.
        """
        request = ImageRequest(
            prompt=prompt,
            quality=quality,
            profile=profile,
            model=model,
            provider=provider,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
        )
        params = self._registry.resolve(request)

        try:
            backend = self._providers[params.provider]
        except KeyError as exc:
            raise ImageRoutingError(
                f"No image provider registered for {params.provider!r}"
            ) from exc

        started = time.perf_counter()
        logger.info(
            "event=image_request_start provider=%s model=%s quality=%s "
            "profile=%s resolution=%s",
            params.provider,
            params.model_id,
            params.quality,
            params.profile,
            params.resolution,
        )
        try:
            image = backend.generate(request.prompt, params)
        except ImageProviderError as exc:
            runtime_ms = (time.perf_counter() - started) * 1000.0
            failure = ImageGenerationMetrics(
                provider=params.provider,
                model=params.model_id,
                runtime_ms=round(runtime_ms, 3),
                estimated_cost=0.0,
                resolution=params.resolution,
                quality=params.quality,
                profile=params.profile,
                success=False,
                error=str(exc),
            )
            self._metrics.record(failure)
            logger.error(
                "event=image_request_failed provider=%s model=%s error=%s",
                params.provider,
                params.model_id,
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            runtime_ms = (time.perf_counter() - started) * 1000.0
            wrapped = ImageProviderError(
                str(exc),
                provider=params.provider,
                model=params.model_id,
            )
            failure = ImageGenerationMetrics(
                provider=params.provider,
                model=params.model_id,
                runtime_ms=round(runtime_ms, 3),
                estimated_cost=0.0,
                resolution=params.resolution,
                quality=params.quality,
                profile=params.profile,
                success=False,
                error=str(exc),
            )
            self._metrics.record(failure)
            raise wrapped from exc

        runtime_ms = (time.perf_counter() - started) * 1000.0
        metrics = ImageGenerationMetrics(
            provider=params.provider,
            model=params.model_id,
            runtime_ms=round(runtime_ms, 3),
            estimated_cost=round(params.cost_per_image, 8),
            resolution=params.resolution,
            quality=params.quality,
            profile=params.profile,
            success=True,
        )
        self._metrics.record(metrics)
        logger.info(
            "event=image_request_complete provider=%s model=%s "
            "runtime_ms=%.1f cost=%.6f resolution=%s",
            metrics.provider,
            metrics.model,
            metrics.runtime_ms,
            metrics.estimated_cost,
            metrics.resolution,
        )
        return ImageGenerationResult(
            prompt=request.prompt,
            image=image,
            params=params,
            metrics=metrics,
        )

    @staticmethod
    def _build_providers(
        config: ImageRouterConfig,
        storage_client: Any | None,
    ) -> dict[str, ImageProvider]:
        providers: dict[str, ImageProvider] = {}
        for name, provider_cfg in config.providers.items():
            providers[name] = _build_provider(provider_cfg, storage_client)
        return providers


def _build_provider(
    cfg: ProviderConfig,
    storage_client: Any | None,
) -> ImageProvider:
    if cfg.type == "runpod":
        from src.services.runpod_client import RunPodClient

        api_key, endpoint_id = _resolve_runpod_credentials(cfg)
        client = RunPodClient(
            api_key=api_key,
            endpoint_id=endpoint_id,
            base_url=cfg.base_url,
        )
        return RunPodImageProvider(
            runpod_client=client,
            storage_client=storage_client,
            name=cfg.name,
        )
    raise ImageConfigError(f"Unsupported image provider type {cfg.type!r}")


def _resolve_runpod_credentials(cfg: ProviderConfig) -> tuple[str, str]:
    import os

    api_key = os.getenv(cfg.api_key_env, "").strip()
    endpoint_id = os.getenv(cfg.endpoint_id_env, "").strip()
    if not api_key or not endpoint_id:
        from src.config import get_settings

        settings = get_settings().image
        if not api_key:
            api_key = settings.api_key.get_secret_value().strip()
        if not endpoint_id:
            endpoint_id = settings.endpoint_id.strip()
    if not api_key:
        raise ImageConfigError(
            f"Missing API key for provider {cfg.name!r} (env {cfg.api_key_env})"
        )
    if not endpoint_id:
        raise ImageConfigError(
            f"Missing endpoint id for provider {cfg.name!r} "
            f"(env {cfg.endpoint_id_env})"
        )
    return api_key, endpoint_id


class ImageEngineAdapter:
    """Adapt :class:`ImageRouter` to the pipeline ``ImageGenerator`` protocol.

    Exposes ``_runpod`` so :func:`~src.services.parallel_images.resolve_image_backend`
    continues to use submit/poll concurrency.
    """

    def __init__(
        self,
        router: ImageRouter,
        *,
        quality: QualityMode = "production",
        profile: GenerationProfileName | None = None,
    ) -> None:
        self._router = router
        self._quality = quality
        self._profile = profile
        self._runpod = _extract_runpod_client(router)

    @property
    def router(self) -> ImageRouter:
        return self._router

    def generate(self, prompt: str) -> Any:
        """Pipeline-compatible generate → :class:`~src.models.image.ImageResult`."""
        result = self._router.generate(
            prompt,
            quality=self._quality,
            profile=self._profile,
        )
        return result.to_image_result()


def _extract_runpod_client(router: ImageRouter) -> Any | None:
    for provider in router.providers.values():
        client = getattr(provider, "client", None)
        if client is not None and callable(getattr(client, "submit", None)):
            return client
    return None


@lru_cache(maxsize=1)
def get_image_router() -> ImageRouter:
    """Return a process-wide :class:`ImageRouter` singleton."""
    return ImageRouter.from_yaml()


def reset_image_router_singleton() -> None:
    """Clear the cached router (tests)."""
    get_image_router.cache_clear()
