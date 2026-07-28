"""Unit tests for the Sprint 5.0 provider-agnostic image engine."""

from __future__ import annotations

from typing import Any

import pytest

from src.image.config import parse_image_config
from src.image.exceptions import ImageConfigError, ImageRoutingError
from src.image.metrics import ImageMetrics
from src.image.models import (
    GenerationParams,
    ImageGenerationMetrics,
    ImageRequest,
)
from src.image.registry import ModelRegistry, merge_generation_params
from src.image.router import ImageEngineAdapter, ImageRouter
from src.models.image import ImageResult


def _sample_config_dict() -> dict[str, Any]:
    return {
        "default_provider": "runpod",
        "default_quality": "production",
        "default_profile": "production",
        "providers": {
            "runpod": {
                "type": "runpod",
                "api_key_env": "RUNPOD_API_KEY",
                "endpoint_id_env": "RUNPOD_ENDPOINT_ID",
                "base_url": "https://api.runpod.ai/v2",
            }
        },
        "models": {
            "flux1-dev": {
                "provider": "runpod",
                "model_id": "black-forest-labs/FLUX.1-dev",
                "quality_modes": ["preview", "production", "experimental"],
                "width": 1024,
                "height": 1024,
                "steps": 28,
                "guidance_scale": 3.5,
                "cost_per_image": 0.02,
            },
            "experimental-only": {
                "provider": "runpod",
                "model_id": "exp-model",
                "quality_modes": ["experimental"],
                "width": 512,
                "height": 512,
                "steps": 4,
                "guidance_scale": 1.0,
                "cost_per_image": 0.001,
            },
        },
        "profiles": {
            "preview": {
                "width": 768,
                "height": 768,
                "steps": 8,
                "guidance_scale": 2.0,
            },
            "production": {
                "width": 1024,
                "height": 1024,
                "steps": 28,
                "guidance_scale": 3.5,
            },
            "cinematic": {
                "width": 1280,
                "height": 720,
                "steps": 30,
                "guidance_scale": 4.0,
            },
        },
        "quality_modes": {
            "preview": {"model": "flux1-dev", "profile": "preview"},
            "production": {"model": "flux1-dev", "profile": "production"},
            "experimental": {"model": "flux1-dev", "profile": "cinematic"},
        },
    }


class _FakeProvider:
    def __init__(self, *, name: str = "runpod") -> None:
        self.name = name
        self.calls: list[tuple[str, GenerationParams]] = []

    def generate(self, prompt: str, params: GenerationParams) -> ImageResult:
        self.calls.append((prompt, params))
        return ImageResult(
            prompt=prompt,
            url="https://example.test/img.png",
            width=params.width,
            height=params.height,
        )


class TestRegistryLoading:
    def test_parse_packaged_shape(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        assert cfg.default_quality == "production"
        assert "flux1-dev" in cfg.models
        assert "cinematic" in cfg.profiles
        assert cfg.quality_route("preview").profile == "preview"

    def test_load_packaged_yaml(self) -> None:
        from src.image.config import load_image_config

        cfg = load_image_config()
        assert "runpod" in cfg.providers
        assert cfg.default_provider == "runpod"
        assert set(cfg.quality_routes) == {"preview", "production", "experimental"}
        assert set(cfg.profiles) == {"preview", "production", "cinematic"}

    def test_unknown_model_in_quality_raises(self) -> None:
        raw = _sample_config_dict()
        raw["quality_modes"]["preview"]["model"] = "missing"
        with pytest.raises(ImageConfigError, match="unknown model"):
            parse_image_config(raw)


class TestProfileMerging:
    def test_profile_overrides_model_defaults(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        model = cfg.model_for("flux1-dev")
        profile = cfg.profile_for("cinematic")
        params = merge_generation_params(
            model=model,
            profile=profile,
            quality="experimental",
            provider="runpod",
        )
        assert params.width == 1280
        assert params.height == 720
        assert params.steps == 30
        assert params.guidance_scale == 4.0
        assert params.resolution == "1280x720"
        assert params.cost_per_image == 0.02

    def test_request_size_overrides_profile(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        registry = ModelRegistry(cfg)
        params = registry.resolve(
            ImageRequest(prompt="a castle", quality="production", width=640, height=640)
        )
        assert params.width == 640
        assert params.height == 640
        assert params.steps == 28  # from production profile
        assert params.profile == "production"

    def test_explicit_profile_override(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        registry = ModelRegistry(cfg)
        params = registry.resolve(
            ImageRequest(prompt="x", quality="production", profile="preview")
        )
        assert params.profile == "preview"
        assert params.width == 768
        assert params.steps == 8


class TestRouterSelection:
    def test_routes_quality_to_provider_and_records_metrics(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        provider = _FakeProvider()
        metrics = ImageMetrics()
        router = ImageRouter(
            ModelRegistry(cfg),
            providers={"runpod": provider},
            metrics=metrics,
        )
        result = router.generate(prompt="a siege", quality="preview")
        assert result.image.url == "https://example.test/img.png"
        assert result.params.quality == "preview"
        assert result.params.profile == "preview"
        assert result.params.width == 768
        assert result.metrics.provider == "runpod"
        assert result.metrics.model == "black-forest-labs/FLUX.1-dev"
        assert result.metrics.resolution == "768x768"
        assert result.metrics.estimated_cost == 0.02
        assert result.metrics.runtime_ms >= 0.0
        assert len(provider.calls) == 1
        snap = metrics.snapshot()
        assert snap["by_provider"]["runpod"]["requests"] == 1

    def test_production_default_profile(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        provider = _FakeProvider()
        router = ImageRouter(ModelRegistry(cfg), providers={"runpod": provider})
        result = router.generate("battle scene")
        assert result.params.quality == "production"
        assert result.params.profile == "production"
        assert result.params.resolution == "1024x1024"

    def test_experimental_uses_cinematic_profile(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        provider = _FakeProvider()
        router = ImageRouter(ModelRegistry(cfg), providers={"runpod": provider})
        result = router.generate("epic vista", quality="experimental")
        assert result.params.profile == "cinematic"
        assert result.params.width == 1280

    def test_unknown_provider_raises(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        router = ImageRouter(ModelRegistry(cfg), providers={})
        with pytest.raises(ImageRoutingError, match="No image provider"):
            router.generate("x", quality="production")

    def test_adapter_returns_image_result(self) -> None:
        cfg = parse_image_config(_sample_config_dict())
        provider = _FakeProvider()
        router = ImageRouter(ModelRegistry(cfg), providers={"runpod": provider})
        adapter = ImageEngineAdapter(router, quality="production")
        image = adapter.generate("pipeline prompt")
        assert isinstance(image, ImageResult)
        assert image.url == "https://example.test/img.png"


class TestMetricsGeneration:
    def test_metrics_snapshot_tracks_success_and_cost(self) -> None:
        metrics = ImageMetrics()
        metrics.record(
            ImageGenerationMetrics(
                provider="runpod",
                model="flux1-dev",
                runtime_ms=1200.0,
                estimated_cost=0.02,
                resolution="1024x1024",
                quality="production",
                profile="production",
                success=True,
            )
        )
        metrics.record(
            ImageGenerationMetrics(
                provider="runpod",
                model="flux1-dev",
                runtime_ms=100.0,
                estimated_cost=0.0,
                resolution="768x768",
                quality="preview",
                profile="preview",
                success=False,
                error="boom",
            )
        )
        snap = metrics.snapshot()
        assert snap["total_requests"] == 2
        assert snap["total_failures"] == 1
        assert snap["total_estimated_cost"] == pytest.approx(0.02)
        assert snap["by_model"]["flux1-dev"]["requests"] == 2
        assert len(snap["recent"]) == 2
