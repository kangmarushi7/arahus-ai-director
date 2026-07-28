"""Provider-agnostic image engine for Arahus.

Public surface::

    from src.image import get_image_router

    result = get_image_router().generate(prompt="...", quality="production")
"""

from __future__ import annotations

from src.image.config import (
    ImageRouterConfig,
    ModelSpec,
    ProfileSpec,
    ProviderConfig,
    QualityRoute,
    load_image_config,
    parse_image_config,
)
from src.image.exceptions import (
    ImageConfigError,
    ImageError,
    ImageProviderError,
    ImageRoutingError,
)
from src.image.metrics import ImageMetrics
from src.image.models import (
    GenerationParams,
    GenerationProfileName,
    ImageGenerationMetrics,
    ImageGenerationResult,
    ImageRequest,
    QualityMode,
)
from src.image.providers import ImageProvider, RunPodImageProvider
from src.image.registry import ModelRegistry, merge_generation_params
from src.image.router import (
    ImageEngineAdapter,
    ImageRouter,
    get_image_router,
    reset_image_router_singleton,
)

__all__ = [
    "GenerationParams",
    "GenerationProfileName",
    "ImageConfigError",
    "ImageEngineAdapter",
    "ImageError",
    "ImageGenerationMetrics",
    "ImageGenerationResult",
    "ImageMetrics",
    "ImageProvider",
    "ImageProviderError",
    "ImageRequest",
    "ImageRouter",
    "ImageRouterConfig",
    "ImageRoutingError",
    "ModelRegistry",
    "ModelSpec",
    "ProfileSpec",
    "ProviderConfig",
    "QualityMode",
    "QualityRoute",
    "RunPodImageProvider",
    "get_image_router",
    "load_image_config",
    "merge_generation_params",
    "parse_image_config",
    "reset_image_router_singleton",
]
