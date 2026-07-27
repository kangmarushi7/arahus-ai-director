"""Composition root: build a configured pipeline from environment variables."""

from __future__ import annotations

import logging

from src.config import get_settings
from src.events import EventBus
from src.models.image import ImageResult
from src.models.pipeline import PipelineResult
from src.models.storyboard import Storyboard
from src.pipeline import DirectorPipeline, ImageGenerator, StorageClient
from src.progress import ProgressCallback
from src.services.r2 import R2StorageClient
from src.services.runpod import RunPodImageGenerator
from src.services.runpod_client import RunPodClient
from src.playground.prompt_playground import PromptPlayground

logger = logging.getLogger(__name__)


class StubImageGenerator:
    """No-op image generator used when RunPod is unavailable."""

    is_stub: bool = True

    def generate(self, prompt: str) -> ImageResult:
        """Return an empty image result without calling a remote GPU."""
        return ImageResult(
            prompt=prompt,
            url=None,
            b64=None,
        )


class StubStorageClient:
    """No-op storage client used when R2 is unavailable."""

    is_stub: bool = True

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Refuse uploads so callers keep a clear status message."""
        raise RuntimeError("R2 storage is not configured")


def _build_image_services() -> tuple[ImageGenerator, StorageClient, bool]:
    """Prefer real RunPod/R2 clients; fall back to stubs only when allowed."""
    settings = get_settings()
    allow_stubs = settings.pipeline.allow_stub_services
    using_stubs = False

    try:
        storage_client: StorageClient = R2StorageClient(settings.storage)
    except RuntimeError as exc:
        if not allow_stubs:
            raise RuntimeError(
                f"R2 storage is not configured ({exc}). "
                "Set R2_* env vars or ALLOW_STUB_SERVICES=true for local dry-runs."
            ) from exc
        logger.warning("Using stub storage client: %s", exc)
        storage_client = StubStorageClient()
        using_stubs = True

    try:
        runpod_client = RunPodClient.from_config(settings.image)
        image_generator: ImageGenerator = RunPodImageGenerator(
            runpod_client=runpod_client,
            storage_client=storage_client,
        )
    except RuntimeError as exc:
        if not allow_stubs:
            raise RuntimeError(
                f"RunPod is not configured ({exc}). "
                "Set RUNPOD_* env vars or ALLOW_STUB_SERVICES=true for local dry-runs."
            ) from exc
        logger.warning("Using stub image generator: %s", exc)
        image_generator = StubImageGenerator()
        using_stubs = True

    return image_generator, storage_client, using_stubs


def build_pipeline() -> DirectorPipeline:
    """Assemble a :class:`DirectorPipeline` from environment configuration.

    Returns:
        A pipeline ready to generate storyboards.

    Raises:
        RuntimeError: If image/storage services are missing and stubs are not allowed.
    """
    settings = get_settings()
    image_generator, storage_client, using_stubs = _build_image_services()

    return DirectorPipeline(
        image_generator=image_generator,
        storage_client=storage_client,
        max_storyboard_retries=settings.pipeline.max_storyboard_retries,
        max_parallel_images=settings.pipeline.image_max_workers,
        event_bus=EventBus(),
        using_stub_services=using_stubs,
    )


def generate_storyboard(topic: str) -> Storyboard:
    """Generate a storyboard for ``topic`` using environment configuration."""
    return build_pipeline().generate(topic).storyboard


def generate_pipeline_result(
    topic: str,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the full pipeline and return every intermediate artifact."""
    return build_pipeline().generate(topic, progress_callback=progress_callback)


def build_prompt_playground() -> PromptPlayground:
    """Assemble a :class:`PromptPlayground` with the configured image generator."""
    image_generator, _storage, _stubs = _build_image_services()
    return PromptPlayground(image_generator=image_generator)


def playground_image_model() -> str:
    """Return the configured image model id for prompt-version labels."""
    return get_settings().image.model_id
