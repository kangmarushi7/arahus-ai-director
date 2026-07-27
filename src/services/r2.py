"""Cloudflare R2 object storage client."""

from __future__ import annotations

import uuid
from functools import lru_cache
from io import BytesIO
from typing import Any

import boto3

from src.config import StorageConfig, get_settings
from src.monitoring.metrics import STAGE_CLOUDFLARE_UPLOAD
from src.monitoring.profiler import measure_stage


@lru_cache(maxsize=1)
def _s3_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
) -> Any:
    """Build an S3 client for the given R2 credentials."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


class R2StorageClient:
    """Uploads bytes to Cloudflare R2 and returns their public URL."""

    def __init__(self, settings: StorageConfig | None = None) -> None:
        """Configure the client from validated storage settings.

        Args:
            settings: Optional override; defaults to :func:`get_settings`.
        """
        self._settings = (settings or get_settings().storage).require_complete()

    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Store ``data`` under a random key and return its public URL.

        Args:
            data: Raw file bytes.
            content_type: MIME type stored alongside the object.

        Returns:
            The public URL of the uploaded object.
        """
        with measure_stage(STAGE_CLOUDFLARE_UPLOAD):
            return self._upload(data, content_type=content_type)

    def _upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        """Perform the R2 upload without profiler instrumentation."""
        extension = "png" if content_type == "image/png" else "bin"
        filename = f"{uuid.uuid4()}.{extension}"
        cfg = self._settings

        client = _s3_client(
            cfg.endpoint.strip(),
            cfg.access_key_id.get_secret_value().strip(),
            cfg.secret_access_key.get_secret_value().strip(),
        )
        client.upload_fileobj(
            BytesIO(data),
            cfg.bucket.strip(),
            filename,
            ExtraArgs={"ContentType": content_type},
        )

        return f"{cfg.public_url.rstrip('/')}/{filename}"


def upload_image(image: Any) -> str:
    """Upload a PIL image as PNG and return its public URL."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return R2StorageClient().upload(buffer.getvalue(), content_type="image/png")
