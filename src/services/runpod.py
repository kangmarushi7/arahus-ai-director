"""ImageGenerator implementation backed by RunPod + optional R2 upload."""

from __future__ import annotations

import base64
import binascii
import logging
from typing import TYPE_CHECKING

from src.models.image import ImageResult

if TYPE_CHECKING:
    from src.pipeline import StorageClient
    from src.services.runpod_client import RunPodClient

logger = logging.getLogger(__name__)


class RunPodImageGeneratorError(Exception):
    """Raised when image generation or storage fails inside the generator."""


class RunPodImageGenerator:
    """:class:`~src.pipeline.ImageGenerator` using RunPod and Cloudflare R2.

    Workflow:
        1. Call :meth:`RunPodClient.generate`.
        2. If the result already has a public URL, return it unchanged.
        3. If the result is base64-only, upload bytes to R2 and return an
           :class:`~src.models.image.ImageResult` with the public URL.

    Always returns an :class:`ImageResult` — never a raw dictionary.
    """

    def __init__(
        self,
        runpod_client: RunPodClient,
        storage_client: StorageClient,
    ) -> None:
        """Inject transport and storage collaborators.

        Args:
            runpod_client: Client that submits/polls RunPod jobs.
            storage_client: Client that uploads raw image bytes and returns a
                publicly reachable URL (typically Cloudflare R2).
        """
        if runpod_client is None:
            raise ValueError("runpod_client is required")
        if storage_client is None:
            raise ValueError("storage_client is required")

        self._runpod = runpod_client
        self._storage = storage_client

    def generate(self, prompt: str) -> ImageResult:
        """Render ``prompt`` via RunPod and ensure a public URL when needed.

        Args:
            prompt: Image prompt describing the scene.

        Returns:
            An :class:`ImageResult` with ``url`` set when RunPod returned a URL
            or when base64 bytes were uploaded to storage.

        Raises:
            ValueError: If ``prompt`` is empty.
            RunPodImageGeneratorError: If RunPod returns neither a URL nor
                decodable base64, or if the R2 upload fails.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        cleaned = " ".join(prompt.split())
        logger.info(
            "event=image_generate_start prompt_chars=%s",
            len(cleaned),
        )

        result = self._runpod.generate(cleaned)
        if not isinstance(result, ImageResult):
            raise RunPodImageGeneratorError(
                "RunPodClient.generate must return ImageResult, got "
                f"{type(result).__name__}"
            )

        if result.url and result.url.strip():
            logger.info(
                "event=image_generate_url_ready url=%s",
                result.url,
            )
            return result.model_copy(
                update={
                    "prompt": cleaned,
                    "url": result.url.strip(),
                }
            )

        if result.b64 and result.b64.strip():
            url = self._upload_base64(result.b64)
            logger.info(
                "event=image_generate_uploaded url=%s",
                url,
            )
            return result.model_copy(
                update={
                    "prompt": cleaned,
                    "url": url,
                    "b64": None,
                }
            )

        raise RunPodImageGeneratorError(
            "RunPod returned neither a public URL nor base64 image data"
        )

    def _upload_base64(self, b64_payload: str) -> str:
        """Decode base64 image bytes and upload them to storage."""
        raw = _decode_image_b64(b64_payload)
        try:
            return self._storage.upload(raw, content_type="image/png")
        except Exception as exc:  # noqa: BLE001 - surface a generator-level error
            raise RunPodImageGeneratorError(
                f"Failed to upload image bytes to storage: {exc}"
            ) from exc


def _decode_image_b64(payload: str) -> bytes:
    """Decode a raw or data-URI base64 image payload into bytes."""
    cleaned = payload.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]

    try:
        return base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise RunPodImageGeneratorError(
            f"Invalid base64 image payload: {exc}"
        ) from exc
