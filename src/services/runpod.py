"""RunPod Serverless image-generation client.

Placeholder implementation: the constructor captures configuration so the
pipeline can be wired end to end, but the network call is intentionally not
implemented yet.
"""

from __future__ import annotations

from src.models.image import ImageResult

DEFAULT_BASE_URL = "https://api.runpod.ai/v2"


class RunPodImageGenerator:
    """Generates images by calling a RunPod Serverless endpoint."""

    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        """Configure the RunPod endpoint.

        Args:
            api_key: RunPod API key.
            endpoint_id: Serverless endpoint identifier.
            base_url: RunPod API base URL.
        """
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not endpoint_id.strip():
            raise ValueError("endpoint_id must be a non-empty string")

        self.api_key = api_key.strip()
        self.endpoint_id = endpoint_id.strip()
        self.base_url = base_url.strip().rstrip("/")

    def generate(self, prompt: str) -> ImageResult:
        """Render one image for ``prompt``.

        Args:
            prompt: Image prompt describing the scene.

        Returns:
            The generated image as an :class:`ImageResult`.

        Raises:
            NotImplementedError: Always, until the endpoint call is wired up.
        """
        raise NotImplementedError(
            "RunPod image generation is not implemented yet; "
            "inject a different ImageGenerator for now."
        )
