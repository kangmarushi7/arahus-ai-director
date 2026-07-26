"""Composition root: build a configured pipeline from environment variables."""

from __future__ import annotations

from src.config import get_settings
from src.models.storyboard import Storyboard
from src.pipeline import DirectorPipeline
from src.services.r2 import R2StorageClient
from src.services.runpod import RunPodImageGenerator


def build_pipeline() -> DirectorPipeline:
    """Assemble a :class:`DirectorPipeline` from environment configuration.

    LLM clients are created inside the pipeline via :func:`create_llm` using
    the models declared in :mod:`src.config`. This function only wires the
    image and storage collaborators.

    Returns:
        A pipeline ready to generate storyboards.

    Raises:
        RuntimeError: If a required environment variable is missing.
    """
    settings = get_settings()
    api_key, endpoint_id = settings.image.require_credentials()
    settings.storage.require_complete()

    image_generator = RunPodImageGenerator(
        api_key=api_key,
        endpoint_id=endpoint_id,
        base_url=settings.image.base_url,
    )

    return DirectorPipeline(
        image_generator=image_generator,
        storage_client=R2StorageClient(),
        max_storyboard_retries=settings.pipeline.max_storyboard_retries,
    )


def generate_storyboard(topic: str) -> Storyboard:
    """Generate a storyboard for ``topic`` using environment configuration.

    Args:
        topic: Historical subject or event.

    Returns:
        The completed storyboard.
    """
    return build_pipeline().generate(topic)
