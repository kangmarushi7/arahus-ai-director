"""Unit tests for Sprint 5.3 provider-agnostic video engine + media layer."""

from __future__ import annotations

from typing import Any

import pytest

from src.media import MediaKind, MediaRouter, register_scene_video
from src.media.request import MediaRequest
from src.models.image import VideoResult
from src.models.memory import ProjectMemory
from src.models.scene_plan import ScenePlan
from src.video.config import load_profile_files, load_video_config, parse_video_config
from src.video.exceptions import VideoConfigError, VideoProviderError, VideoRoutingError
from src.video.metrics import VideoMetrics
from src.video.models import VideoGenerationParams, VideoRequest
from src.video.prompt import compose_video_prompt_from_scene_plan
from src.video.providers.runpod import RunPodVideoProvider
from src.video.registry import ModelRegistry, merge_generation_params
from src.video.router import VideoEngineAdapter, VideoRouter


def _sample_config_dict() -> dict[str, Any]:
    return {
        "default_provider": "runpod",
        "default_quality": "production",
        "default_profile": "production",
        "providers": {
            "runpod": {
                "type": "runpod",
                "api_key_env": "RUNPOD_API_KEY",
                "endpoint_id_env": "RUNPOD_VIDEO_ENDPOINT_ID",
                "enabled": False,
            }
        },
        "models": {
            "video-placeholder": {
                "provider": "runpod",
                "model_id": "video-placeholder",
                "quality_modes": ["preview", "production", "experimental"],
                "duration": 5,
                "fps": 24,
                "width": 720,
                "height": 1280,
                "aspect_ratio": "9:16",
                "cost_per_second": 0.05,
                "motion": "natural",
            }
        },
        "profiles": {
            "preview": {
                "duration": 5,
                "fps": 16,
                "width": 720,
                "height": 1280,
                "aspect_ratio": "9:16",
                "quality": "fast",
                "motion": "basic",
            },
            "production": {
                "duration": 5,
                "fps": 24,
                "width": 720,
                "height": 1280,
                "aspect_ratio": "9:16",
                "quality": "high",
                "motion": "natural",
            },
            "cinematic": {
                "duration": 8,
                "fps": 24,
                "width": 1280,
                "height": 720,
                "aspect_ratio": "16:9",
                "quality": "high",
                "motion": "smooth",
            },
        },
        "quality_modes": {
            "preview": {"model": "video-placeholder", "profile": "preview"},
            "production": {"model": "video-placeholder", "profile": "production"},
            "experimental": {"model": "video-placeholder", "profile": "cinematic"},
        },
    }


class _FakeVideoProvider:
    name = "runpod"
    kind = MediaKind.VIDEO

    def __init__(self) -> None:
        self.calls: list[tuple[VideoRequest, VideoGenerationParams]] = []

    def healthcheck(self) -> dict[str, Any]:
        return {"ready": True}

    def generate(
        self,
        request: VideoRequest,
        params: VideoGenerationParams,
    ) -> VideoResult:
        self.calls.append((request, params))
        return VideoResult(
            prompt=request.prompt,
            url="https://example.test/scene.mp4",
            duration_seconds=params.duration,
            fps=params.fps,
            width=params.width,
            height=params.height,
            source_image=request.source_image,
            source_image_urls=list(request.source_image_urls),
        )


class TestMediaAbstraction:
    def test_media_request_requires_prompt(self) -> None:
        with pytest.raises(Exception):
            MediaRequest(prompt="   ")

    def test_video_router_is_media_router(self) -> None:
        assert issubclass(VideoRouter, MediaRouter)


class TestRequestValidation:
    def test_text_to_video_mode(self) -> None:
        req = VideoRequest(prompt="Napoleon crosses the Alps")
        assert req.mode == "text-to-video"
        assert req.source_image is None

    def test_image_to_video_mode_from_source_image(self) -> None:
        req = VideoRequest(
            prompt="camera slowly pushes in",
            source_image="https://cdn.example/scene.png",
        )
        assert req.mode == "image-to-video"
        assert req.source_image_urls == ["https://cdn.example/scene.png"]

    def test_image_to_video_mode_from_urls(self) -> None:
        req = VideoRequest(
            prompt="motion",
            source_image_urls=["https://cdn.example/a.png"],
        )
        assert req.mode == "image-to-video"
        assert req.source_image == "https://cdn.example/a.png"

    def test_empty_prompt_rejected(self) -> None:
        with pytest.raises(Exception):
            VideoRequest(prompt="")


class TestProfileLoading:
    def test_packaged_profile_files_load(self) -> None:
        profiles = load_profile_files()
        assert set(profiles) >= {"preview", "production", "cinematic"}
        assert profiles["preview"]["fps"] == 16
        assert profiles["cinematic"]["duration"] == 8
        assert profiles["cinematic"]["motion"] == "smooth"

    def test_packaged_video_config_merges_profiles(self) -> None:
        config = load_video_config()
        assert "preview" in config.profiles
        assert config.profiles["production"].fps == 24
        assert config.profiles["cinematic"].duration == 8.0
        assert config.default_provider == "runpod"

    def test_parse_rejects_unknown_profile(self) -> None:
        raw = _sample_config_dict()
        raw["profiles"]["ultra"] = {"fps": 60}
        with pytest.raises(VideoConfigError):
            parse_video_config(raw, profiles_dir=None)


class TestRegistryAndRouting:
    def test_profile_merge_precedence(self) -> None:
        config = parse_video_config(_sample_config_dict(), profiles_dir=None)
        registry = ModelRegistry(config)
        params = registry.resolve(
            VideoRequest(prompt="test", quality="preview", duration=3, fps=12)
        )
        assert params.profile == "preview"
        assert params.duration == 3.0  # explicit override
        assert params.fps == 12
        assert params.width == 720
        assert params.motion == "basic"

    def test_cinematic_profile_from_experimental_quality(self) -> None:
        config = parse_video_config(_sample_config_dict(), profiles_dir=None)
        params = ModelRegistry(config).resolve(
            VideoRequest(prompt="test", quality="experimental")
        )
        assert params.profile == "cinematic"
        assert params.duration == 8.0
        assert params.width == 1280
        assert params.height == 720
        assert params.motion == "smooth"

    def test_merge_generation_params_helper(self) -> None:
        config = parse_video_config(_sample_config_dict(), profiles_dir=None)
        model = config.model_for("video-placeholder")
        profile = config.profile_for("production")
        params = merge_generation_params(
            model=model,
            profile=profile,
            quality="production",
            provider="runpod",
            mode="text-to-video",
        )
        assert params.resolution == "720x1280"
        assert params.estimated_cost == pytest.approx(0.25)

    def test_unknown_provider_raises(self) -> None:
        config = parse_video_config(_sample_config_dict(), profiles_dir=None)
        with pytest.raises(VideoRoutingError):
            ModelRegistry(config).resolve(
                VideoRequest(prompt="x", provider="missing")
            )


class TestVideoRouterGenerate:
    def test_text_to_video_generate(self) -> None:
        fake = _FakeVideoProvider()
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None),
            providers={"runpod": fake},
            metrics=VideoMetrics(),
        )
        result = router.generate("army marches through snow", profile="production")
        assert result.url == "https://example.test/scene.mp4"
        assert result.request_mode == "text-to-video"
        assert result.params.fps == 24
        assert result.metrics.success is True
        assert result.metrics.provider == "runpod"
        assert result.metrics.resolution == "720x1280"
        assert result.metrics.duration == 5.0
        assert result.metrics.gpu_seconds >= 0.0
        assert "cost" in result.metrics.to_dict()
        assert len(fake.calls) == 1

    def test_image_to_video_generate(self) -> None:
        fake = _FakeVideoProvider()
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None),
            providers={"runpod": fake},
        )
        result = router.generate(
            VideoRequest(
                prompt="slow dolly in",
                source_image="https://cdn.example/napoleon.png",
                profile="cinematic",
            )
        )
        assert result.request_mode == "image-to-video"
        assert result.video.source_image == "https://cdn.example/napoleon.png"
        assert result.params.duration == 8.0
        assert result.params.motion == "smooth"

    def test_disabled_runpod_provider_refuses_generation(self) -> None:
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None)
        )
        with pytest.raises(VideoProviderError, match="disabled"):
            router.generate("should fail without wired model")

    def test_live_runpod_provider_with_injected_client(self) -> None:
        class _Client:
            def submit(self, job_input):
                assert job_input["prompt"]
                assert job_input["model_id"] == "video-placeholder"
                return "job-1"

            def poll(self, job_id):
                assert job_id == "job-1"
                return {
                    "status": "COMPLETED",
                    "output": {
                        "url": "https://cdn.example/out.mp4",
                        "duration_seconds": 5,
                        "fps": 24,
                    },
                }

        provider = RunPodVideoProvider(
            enabled=True,
            endpoint_id="ep",
            api_key="key",
            client=_Client(),
        )
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None),
            providers={"runpod": provider},
        )
        # Sample config still points at video-placeholder model id
        result = router.generate("army advances", profile="production")
        assert result.url == "https://cdn.example/out.mp4"
        assert result.metrics.success is True

    def test_adapter_returns_video_result(self) -> None:
        fake = _FakeVideoProvider()
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None),
            providers={"runpod": fake},
        )
        adapter = VideoEngineAdapter(router, profile="preview")
        video = adapter.generate("preview clip")
        assert isinstance(video, VideoResult)
        assert video.fps == 16


class TestMetrics:
    def test_metrics_snapshot_records_cost_and_gpu(self) -> None:
        metrics = VideoMetrics()
        fake = _FakeVideoProvider()
        router = VideoRouter.from_config(
            parse_video_config(_sample_config_dict(), profiles_dir=None),
            providers={"runpod": fake},
            metrics=metrics,
        )
        router.generate("clip one", quality="production")
        snap = metrics.snapshot()
        assert snap["total_requests"] == 1
        assert snap["total_failures"] == 0
        assert snap["total_estimated_cost"] == pytest.approx(0.25)
        assert "runpod" in snap["by_provider"]
        assert snap["recent"][0]["model"] == "video-placeholder"
        assert "gpu_seconds" in snap["recent"][0]


class TestAssetRegistration:
    def test_register_scene_video_stable_id(self) -> None:
        memory = ProjectMemory(project_id="demo_vid", topic="Alps")
        first = register_scene_video(
            memory,
            scene_id=3,
            title="Crossing",
            url="https://cdn.example/scene3.mp4",
            source_image_urls=["https://cdn.example/scene3.png"],
        )
        assert first.kind.value == "video"
        assert first.slug == "scene_3_video"
        assert first.refs["url"] == "https://cdn.example/scene3.mp4"
        assert first.id >= 1

        second = register_scene_video(
            memory,
            scene_id=3,
            title="Crossing",
            url="https://cdn.example/scene3-v2.mp4",
        )
        assert second.id == first.id  # stable reuse by slug
        assert second.refs["url"] == "https://cdn.example/scene3-v2.mp4"

    def test_video_result_can_carry_asset_id(self) -> None:
        memory = ProjectMemory(project_id="demo_vid2", topic="Alps")
        record = register_scene_video(memory, scene_id=1, url="https://x/v.mp4")
        result = VideoResult(
            prompt="motion",
            url="https://x/v.mp4",
            asset_id=record.id,
        )
        assert result.asset_id == record.id


class TestVideoPromptFromScenePlan:
    def test_compose_includes_cinematic_language(self) -> None:
        scene = ScenePlan(
            id=1,
            title="Crossing",
            description="Napoleon leads the column over the alpine pass at dawn " * 3,
            subject="Napoleon on horseback",
            environment="snowy pass",
            action="army advances",
            camera_shot="wide establishing",
            camera_movement="Slow Dolly In",
            camera_angle="low angle",
            lens="35mm anamorphic",
            lighting="Golden Hour",
            emotion="Tension",
            composition="leading lines",
        )
        prompt = compose_video_prompt_from_scene_plan(scene)
        assert "Slow Dolly In" in prompt
        assert "Tension" in prompt
        assert "Golden Hour" in prompt
        assert "wide establishing" in prompt
