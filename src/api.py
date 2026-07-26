"""Composition root: build a configured pipeline from environment variables."""

from __future__ import annotations

import logging

from src.config import get_settings
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

    def generate(self, prompt: str) -> ImageResult:
        """Return an empty image result without calling a remote GPU."""
        return ImageResult(
            prompt=prompt,
            url=None,
            b64=None,
        )


class StubStorageClient:
    """No-op storage client used when R2 is unavailable."""

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Refuse uploads so callers keep a clear status message."""
        raise RuntimeError("R2 storage is not configured")


def _build_image_services() -> tuple[ImageGenerator, StorageClient]:
    """Prefer real RunPod/R2 clients; fall back to stubs for local studio use."""
    settings = get_settings()

    try:
        storage_client: StorageClient = R2StorageClient(settings.storage)
    except RuntimeError as exc:
        logger.warning("Using stub storage client: %s", exc)
        storage_client = StubStorageClient()

    try:
        runpod_client = RunPodClient.from_config(settings.image)
        image_generator: ImageGenerator = RunPodImageGenerator(
            runpod_client=runpod_client,
            storage_client=storage_client,
        )
    except RuntimeError as exc:
        logger.warning("Using stub image generator: %s", exc)
        image_generator = StubImageGenerator()

    return image_generator, storage_client


def build_pipeline() -> DirectorPipeline:
    """Assemble a :class:`DirectorPipeline` from environment configuration.

    LLM clients are created inside the pipeline via :func:`create_llm`. Image
    and storage collaborators use real services when configured, otherwise
    safe stubs so the studio can still run research → review.

    Returns:
        A pipeline ready to generate storyboards.
    """
    settings = get_settings()
    image_generator, storage_client = _build_image_services()

    return DirectorPipeline(
        image_generator=image_generator,
        storage_client=storage_client,
        max_storyboard_retries=settings.pipeline.max_storyboard_retries,
    )


def generate_storyboard(topic: str) -> Storyboard:
    """Generate a storyboard for ``topic`` using environment configuration.

    Args:
        topic: Historical subject or event.

    Returns:
        The completed storyboard from the pipeline result.
    """
    return build_pipeline().generate(topic).storyboard


def generate_pipeline_result(
    topic: str,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the full pipeline and return every intermediate artifact.

    Args:
        topic: Historical subject or event.
        progress_callback: Optional ``(message, fraction)`` sink for live UIs.

    Returns:
        The complete :class:`PipelineResult`.
    """
    return build_pipeline().generate(topic, progress_callback=progress_callback)


def build_prompt_playground() -> PromptPlayground:
    """Assemble a :class:`PromptPlayground` with the configured image generator.

    Returns:
        A playground ready for per-scene prompt versioning and image renders.
    """
    image_generator, _storage = _build_image_services()
    return PromptPlayground(image_generator=image_generator)


def playground_image_model() -> str:
    """Return the configured image model id for prompt-version labels."""
    return get_settings().image.model_id
