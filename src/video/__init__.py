"""Provider-agnostic video engine for Arahus.

Public surface::

    from src.video import get_video_router, VideoRequest

    result = get_video_router().generate(
        VideoRequest(prompt="...", profile="production")
    )

Architecture only in Sprint 5.3 — inject a fake provider in tests; the default
RunPod provider refuses generation until a concrete video model is wired.
"""

from __future__ import annotations

from src.video.config import (
    ModelSpec,
    ProfileSpec,
    ProviderConfig,
    QualityRoute,
    VideoRouterConfig,
    load_profile_files,
    load_video_config,
    parse_video_config,
)
from src.video.exceptions import (
    VideoConfigError,
    VideoError,
    VideoProviderError,
    VideoRoutingError,
)
from src.video.metrics import VideoMetrics
from src.video.models import (
    VideoGenerationMetrics,
    VideoGenerationParams,
    VideoGenerationResult,
    VideoMode,
    VideoRequest,
)
from src.video.prompt import (
    cinematic_fields_for_video,
    compose_video_prompt_from_scene_plan,
)
from src.video.providers import RunPodVideoProvider, VideoProvider
from src.video.registry import ModelRegistry, merge_generation_params
from src.video.router import (
    VideoEngineAdapter,
    VideoRouter,
    get_video_router,
    reset_video_router_singleton,
)

__all__ = [
    "ModelRegistry",
    "ModelSpec",
    "ProfileSpec",
    "ProviderConfig",
    "QualityRoute",
    "RunPodVideoProvider",
    "VideoConfigError",
    "VideoEngineAdapter",
    "VideoError",
    "VideoGenerationMetrics",
    "VideoGenerationParams",
    "VideoGenerationResult",
    "VideoMetrics",
    "VideoMode",
    "VideoProvider",
    "VideoProviderError",
    "VideoRequest",
    "VideoRouter",
    "VideoRouterConfig",
    "VideoRoutingError",
    "cinematic_fields_for_video",
    "compose_video_prompt_from_scene_plan",
    "get_video_router",
    "load_profile_files",
    "load_video_config",
    "merge_generation_params",
    "parse_video_config",
    "reset_video_router_singleton",
]
