"""YAML-driven image model registry with profile merging."""

from __future__ import annotations

from typing import Any

from src.image.config import ImageRouterConfig, ModelSpec, ProfileSpec, load_image_config
from src.image.exceptions import ImageConfigError, ImageRoutingError
from src.image.models import (
    GenerationParams,
    GenerationProfileName,
    ImageRequest,
    QualityMode,
)


class ModelRegistry:
    """Resolve quality modes + profiles into concrete generation params."""

    def __init__(self, config: ImageRouterConfig) -> None:
        if config is None:
            raise ValueError("config is required")
        self._config = config

    @classmethod
    def from_yaml(cls, path: str | None = None) -> ModelRegistry:
        """Build a registry from packaged or custom YAML."""
        return cls(load_image_config(path))

    @property
    def config(self) -> ImageRouterConfig:
        return self._config

    def list_models(self) -> list[ModelSpec]:
        return list(self._config.models.values())

    def list_profiles(self) -> list[ProfileSpec]:
        return list(self._config.profiles.values())

    def resolve(self, request: ImageRequest) -> GenerationParams:
        """Merge quality route, model defaults, profile overrides, and request."""
        quality: QualityMode = request.quality or self._config.default_quality
        route = self._config.quality_route(quality)

        model_key = (request.model or route.model).strip().lower()
        try:
            model = self._config.model_for(model_key)
        except ImageConfigError as exc:
            raise ImageRoutingError(str(exc)) from exc

        if quality not in model.quality_modes:
            raise ImageRoutingError(
                f"Model {model_key!r} does not support quality mode {quality!r}"
            )

        profile_name: GenerationProfileName = (
            request.profile or route.profile or self._config.default_profile
        )
        try:
            profile = self._config.profile_for(profile_name)
        except ImageConfigError as exc:
            raise ImageRoutingError(str(exc)) from exc

        provider = (request.provider or model.provider).strip()
        if provider not in self._config.providers:
            raise ImageRoutingError(f"Unknown image provider {provider!r}")

        return merge_generation_params(
            model=model,
            profile=profile,
            quality=quality,
            provider=provider,
            width=request.width,
            height=request.height,
        )


def merge_generation_params(
    *,
    model: ModelSpec,
    profile: ProfileSpec,
    quality: QualityMode,
    provider: str,
    width: int | None = None,
    height: int | None = None,
) -> GenerationParams:
    """Merge model defaults ← profile overrides ← explicit request sizes.

    Precedence (lowest → highest):
    1. Model registry defaults
    2. Generation profile
    3. Explicit request width/height
    """
    extras: dict[str, Any] = dict(model.extras)
    extras.update(dict(profile.extras))

    return GenerationParams(
        model_key=model.key,
        model_id=model.model_id,
        provider=provider,
        quality=quality,
        profile=profile.name,
        width=int(width if width is not None else (profile.width or model.width)),
        height=int(height if height is not None else (profile.height or model.height)),
        steps=int(profile.steps if profile.steps is not None else model.steps),
        guidance_scale=float(
            profile.guidance_scale
            if profile.guidance_scale is not None
            else model.guidance_scale
        ),
        cost_per_image=float(model.cost_per_image),
        extras=extras,
    )
