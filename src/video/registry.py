"""YAML-driven video model registry with profile merging."""

from __future__ import annotations

from typing import Any

from src.media.request import GenerationProfileName, QualityMode
from src.video.config import ModelSpec, ProfileSpec, VideoRouterConfig, load_video_config
from src.video.exceptions import VideoConfigError, VideoRoutingError
from src.video.models import VideoGenerationParams, VideoRequest


class ModelRegistry:
    """Resolve quality modes + profiles into concrete video generation params."""

    def __init__(self, config: VideoRouterConfig) -> None:
        if config is None:
            raise ValueError("config is required")
        self._config = config

    @classmethod
    def from_yaml(cls, path: str | None = None) -> ModelRegistry:
        """Build a registry from packaged or custom YAML."""
        return cls(load_video_config(path))

    @property
    def config(self) -> VideoRouterConfig:
        return self._config

    def list_models(self) -> list[ModelSpec]:
        return list(self._config.models.values())

    def list_profiles(self) -> list[ProfileSpec]:
        return list(self._config.profiles.values())

    def resolve(self, request: VideoRequest) -> VideoGenerationParams:
        """Merge quality route, model defaults, profile overrides, and request."""
        quality: QualityMode = request.quality or self._config.default_quality
        route = self._config.quality_route(quality)

        model_key = (request.model or route.model).strip().lower()
        try:
            model = self._config.model_for(model_key)
        except VideoConfigError as exc:
            raise VideoRoutingError(str(exc)) from exc

        if quality not in model.quality_modes:
            raise VideoRoutingError(
                f"Model {model_key!r} does not support quality mode {quality!r}"
            )

        profile_name: GenerationProfileName = (
            request.profile or route.profile or self._config.default_profile
        )
        try:
            profile = self._config.profile_for(profile_name)
        except VideoConfigError as exc:
            raise VideoRoutingError(str(exc)) from exc

        provider = (request.provider or model.provider).strip()
        if provider not in self._config.providers:
            raise VideoRoutingError(f"Unknown video provider {provider!r}")

        return merge_generation_params(
            model=model,
            profile=profile,
            quality=quality,
            provider=provider,
            mode=request.mode,
            duration=request.duration,
            fps=request.fps,
            width=request.width,
            height=request.height,
            aspect_ratio=request.aspect_ratio,
            motion=request.motion,
        )


def merge_generation_params(
    *,
    model: ModelSpec,
    profile: ProfileSpec,
    quality: QualityMode,
    provider: str,
    mode: str = "text-to-video",
    duration: float | None = None,
    fps: int | None = None,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
    motion: str | None = None,
) -> VideoGenerationParams:
    """Merge model defaults ← profile overrides ← explicit request fields.

    Precedence (lowest → highest):
    1. Model registry defaults
    2. Generation profile (preview / production / cinematic)
    3. Explicit request overrides
    """
    extras: dict[str, Any] = dict(model.extras)
    extras.update(dict(profile.extras))
    if profile.quality_label:
        extras["quality_label"] = profile.quality_label

    resolved_duration = float(
        duration
        if duration is not None
        else (profile.duration if profile.duration is not None else model.duration)
    )
    resolved_fps = int(
        fps if fps is not None else (profile.fps if profile.fps is not None else model.fps)
    )
    resolved_width = int(
        width
        if width is not None
        else (profile.width if profile.width is not None else model.width)
    )
    resolved_height = int(
        height
        if height is not None
        else (profile.height if profile.height is not None else model.height)
    )
    resolved_aspect = (
        aspect_ratio
        or profile.aspect_ratio
        or model.aspect_ratio
        or "9:16"
    )
    resolved_motion = (motion or profile.motion or model.motion or "").strip()

    return VideoGenerationParams(
        model_key=model.key,
        model_id=model.model_id,
        provider=provider,
        quality=quality,
        profile=profile.name,
        mode=mode,  # type: ignore[arg-type]
        duration=resolved_duration,
        fps=resolved_fps,
        width=resolved_width,
        height=resolved_height,
        aspect_ratio=str(resolved_aspect),
        motion=resolved_motion,
        cost_per_second=float(model.cost_per_second),
        extras=extras,
    )
