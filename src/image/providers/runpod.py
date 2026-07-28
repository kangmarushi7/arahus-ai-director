"""RunPod image provider wrapping the existing RunPod client."""

from __future__ import annotations

import base64
import binascii
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from src.image.exceptions import ImageProviderError
from src.image.models import GenerationParams
from src.models.image import ImageResult

if TYPE_CHECKING:
    from src.pipeline import StorageClient
    from src.services.runpod_client import RunPodClient

logger = logging.getLogger(__name__)


class RunPodImageProvider:
    """:class:`~src.image.providers.base.ImageProvider` backed by RunPod + R2.

    Preserves the existing RunPod submit/poll/upload behaviour while accepting
    resolved :class:`~src.image.models.GenerationParams` from the registry.
    """

    def __init__(
        self,
        runpod_client: RunPodClient,
        storage_client: StorageClient | None = None,
        *,
        name: str = "runpod",
    ) -> None:
        if runpod_client is None:
            raise ValueError("runpod_client is required")
        self._client = runpod_client
        self._storage = storage_client
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def client(self) -> RunPodClient:
        """Underlying RunPod HTTP client (used by parallel job backends)."""
        return self._client

    def generate(self, prompt: str, params: GenerationParams) -> ImageResult:
        """Generate via RunPod, applying profile size/steps for this request."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        cleaned = " ".join(prompt.split())

        logger.info(
            "event=image_provider_generate provider=%s model=%s "
            "resolution=%s steps=%s guidance=%s prompt_chars=%s",
            self._name,
            params.model_id,
            params.resolution,
            params.steps,
            params.guidance_scale,
            len(cleaned),
        )

        try:
            with _temporary_client_params(
                self._client,
                width=params.width,
                height=params.height,
                steps=params.steps,
                guidance_scale=params.guidance_scale,
            ):
                result = self._client.generate(cleaned)
        except Exception as exc:  # noqa: BLE001 - wrap as provider error
            raise ImageProviderError(
                f"RunPod generation failed: {exc}",
                provider=self._name,
                model=params.model_id,
            ) from exc

        if not isinstance(result, ImageResult):
            raise ImageProviderError(
                f"RunPod returned unexpected type {type(result).__name__}",
                provider=self._name,
                model=params.model_id,
            )

        # Prefer provider dimensions when the worker did not return them.
        updates: dict[str, object] = {"prompt": cleaned}
        if result.width is None:
            updates["width"] = params.width
        if result.height is None:
            updates["height"] = params.height

        if result.url and result.url.strip():
            updates["url"] = result.url.strip()
            return result.model_copy(update=updates)

        if result.b64 and result.b64.strip():
            if self._storage is None:
                raise ImageProviderError(
                    "RunPod returned base64 data but no storage client is configured",
                    provider=self._name,
                    model=params.model_id,
                )
            try:
                url = self._storage.upload(
                    _decode_image_b64(result.b64),
                    content_type="image/png",
                )
            except Exception as exc:  # noqa: BLE001
                raise ImageProviderError(
                    f"Failed to upload image bytes to storage: {exc}",
                    provider=self._name,
                    model=params.model_id,
                ) from exc
            updates["url"] = url
            updates["b64"] = None
            return result.model_copy(update=updates)

        raise ImageProviderError(
            "RunPod returned neither a public URL nor base64 image data",
            provider=self._name,
            model=params.model_id,
        )


@contextmanager
def _temporary_client_params(
    client: RunPodClient,
    *,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
) -> Iterator[None]:
    """Apply generation params for one call without permanently mutating defaults."""
    previous = (
        client.width,
        client.height,
        client.num_inference_steps,
        client.guidance_scale,
    )
    client.width = int(width)
    client.height = int(height)
    client.num_inference_steps = int(steps)
    client.guidance_scale = float(guidance_scale)
    try:
        yield
    finally:
        (
            client.width,
            client.height,
            client.num_inference_steps,
            client.guidance_scale,
        ) = previous


def _decode_image_b64(payload: str) -> bytes:
    cleaned = payload.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]
    try:
        return base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ImageProviderError(f"Invalid base64 image payload: {exc}") from exc
