"""RunPod video provider — Wan 2.1 (and compatible) serverless endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

import requests

from src.media.base import MediaKind
from src.models.image import VideoResult
from src.services.runpod_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    RunPodClientError,
    RunPodJobError,
    RunPodOutputError,
    RunPodRequestError,
    RunPodTimeoutError,
)
from src.video.exceptions import VideoProviderError
from src.video.models import VideoGenerationParams, VideoRequest

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})
_FAILURE_STATUSES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})
_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Video jobs are long; default poll cadence is slightly slower than images.
_DEFAULT_VIDEO_POLL_INTERVAL = 3.0
_DEFAULT_VIDEO_POLL_TIMEOUT = 600.0


class RunPodVideoProvider:
    """Production RunPod video backend (Wan 2.1 / compatible workers).

    Live generation requires ``enabled=True``, ``RUNPOD_API_KEY``, and
    ``RUNPOD_VIDEO_ENDPOINT_ID``. Inject ``session`` in tests to avoid network.
    """

    def __init__(
        self,
        *,
        name: str = "runpod",
        enabled: bool = False,
        endpoint_id: str | None = None,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = _DEFAULT_VIDEO_POLL_INTERVAL,
        poll_timeout_seconds: float = _DEFAULT_VIDEO_POLL_TIMEOUT,
        session: requests.Session | None = None,
        client: Any | None = None,
    ) -> None:
        self._name = name
        self._enabled = enabled
        self._endpoint_id = (endpoint_id or "").strip()
        self._api_key = (api_key or "").strip()
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._request_timeout = max(
            DEFAULT_REQUEST_TIMEOUT_SECONDS, float(timeout_seconds) / 10.0
        )
        self._poll_interval = max(0.5, float(poll_interval_seconds))
        self._poll_timeout = max(30.0, float(poll_timeout_seconds))
        self._session = session or requests.Session()
        self._client = client  # optional duck-typed submit/poll helper for tests
        self._max_retries = DEFAULT_MAX_RETRIES
        self._retry_backoff = DEFAULT_RETRY_BACKOFF_SECONDS

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> MediaKind:
        return MediaKind.VIDEO

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def client(self) -> Any | None:
        return self._client

    def healthcheck(self) -> dict[str, Any]:
        ready = bool(
            self._enabled and self._endpoint_id and self._api_key
        )
        return {
            "provider": self._name,
            "kind": self.kind.value,
            "enabled": self._enabled,
            "endpoint_configured": bool(self._endpoint_id),
            "credentials_configured": bool(self._api_key),
            "ready": ready,
            "detail": (
                "Ready for Wan 2.1 / compatible RunPod video jobs"
                if ready
                else "Set RUNPOD_API_KEY + RUNPOD_VIDEO_ENDPOINT_ID and enabled=true"
            ),
        }

    def generate(
        self,
        request: VideoRequest,
        params: VideoGenerationParams,
    ) -> VideoResult:
        """Submit a video job, poll to completion, return :class:`VideoResult`."""
        if not self._enabled:
            raise VideoProviderError(
                "RunPod video provider is disabled in video_router.yaml "
                "(providers.runpod.enabled=false).",
                provider=self._name,
                model=params.model_id,
            )
        if not self._endpoint_id or not self._api_key:
            raise VideoProviderError(
                "RunPod video endpoint is not configured. Set RUNPOD_API_KEY and "
                "RUNPOD_VIDEO_ENDPOINT_ID.",
                provider=self._name,
                model=params.model_id,
            )

        job_input = self._build_input(request, params)
        logger.info(
            "event=video_provider_generate provider=%s model=%s mode=%s "
            "duration=%s resolution=%sx%s endpoint=%s",
            self._name,
            params.model_id,
            request.mode,
            params.duration,
            params.width,
            params.height,
            self._endpoint_id,
        )

        try:
            if self._client is not None:
                job_id = self._client.submit(job_input)
                payload = self._client.poll(job_id)
            else:
                job_id = self._submit(job_input)
                payload = self._poll(job_id)
            return self._parse_result(request, params, job_id=job_id, payload=payload)
        except VideoProviderError:
            raise
        except (RunPodClientError, requests.RequestException) as exc:
            raise VideoProviderError(
                f"RunPod video generation failed: {exc}",
                provider=self._name,
                model=params.model_id,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise VideoProviderError(
                f"RunPod video generation failed: {exc}",
                provider=self._name,
                model=params.model_id,
            ) from exc

    @staticmethod
    def _build_input(
        request: VideoRequest, params: VideoGenerationParams
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "model_id": params.model_id,
            "duration": params.duration,
            "fps": params.fps,
            "width": params.width,
            "height": params.height,
            "aspect_ratio": params.aspect_ratio,
            "motion": params.motion,
            "mode": request.mode,
        }
        if request.source_image:
            payload["source_image"] = request.source_image
        if request.source_image_urls:
            payload["source_image_urls"] = list(request.source_image_urls)
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def _run_url(self) -> str:
        return f"{self._base_url}/{self._endpoint_id}/run"

    def _status_url(self, job_id: str) -> str:
        return f"{self._base_url}/{self._endpoint_id}/status/{job_id}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _submit(self, job_input: dict[str, Any]) -> str:
        body = {"input": job_input}
        response = self._request_json("POST", self._run_url(), json_body=body)
        job_id = response.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise RunPodClientError(
                f"RunPod video submit response missing job id: {response!r}"
            )
        logger.info(
            "event=runpod_video_submitted endpoint_id=%s job_id=%s",
            self._endpoint_id,
            job_id,
        )
        return job_id.strip()

    def _poll(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._poll_timeout
        url = self._status_url(job_id)
        while True:
            payload = self._request_json("GET", url)
            status = str(payload.get("status") or "").upper()
            if status in _TERMINAL_STATUSES:
                if status in _FAILURE_STATUSES:
                    detail = payload.get("error") or payload.get("output")
                    raise RunPodJobError(
                        f"RunPod video job {job_id!r} ended with {status}: {detail!r}",
                        job_id=job_id,
                        status=status,
                        payload=payload,
                    )
                return payload
            if time.monotonic() >= deadline:
                raise RunPodTimeoutError(
                    f"Timed out after {self._poll_timeout:.0f}s waiting for "
                    f"video job {job_id!r}",
                    job_id=job_id,
                )
            time.sleep(self._poll_interval)

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    timeout=self._request_timeout,
                )
                if response.status_code in _RETRYABLE_HTTP_STATUS:
                    raise RunPodRequestError(
                        f"Retryable HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=response.text[:500],
                    )
                if response.status_code >= 400:
                    raise RunPodRequestError(
                        f"RunPod HTTP {response.status_code}: {response.text[:500]}",
                        status_code=response.status_code,
                        response_body=response.text[:500],
                    )
                data = response.json()
                if not isinstance(data, dict):
                    raise RunPodClientError(
                        f"Expected JSON object from RunPod, got {type(data).__name__}"
                    )
                return data
            except (RunPodRequestError, requests.RequestException) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                time.sleep(self._retry_backoff * attempt)
        raise RunPodRequestError(
            f"RunPod video request failed after {self._max_retries} attempts: "
            f"{last_error}"
        )

    def _parse_result(
        self,
        request: VideoRequest,
        params: VideoGenerationParams,
        *,
        job_id: str,
        payload: Mapping[str, Any],
    ) -> VideoResult:
        output = payload.get("output")
        if isinstance(output, list) and output:
            output = output[0]
        if not isinstance(output, Mapping):
            output = {}

        url = (
            output.get("url")
            or output.get("video_url")
            or output.get("mp4_url")
            or payload.get("url")
        )
        if isinstance(url, str) and url.startswith("http"):
            return VideoResult(
                prompt=request.prompt,
                url=url,
                duration_seconds=_as_float(
                    output.get("duration_seconds") or output.get("duration"),
                    default=params.duration,
                ),
                fps=_as_int(output.get("fps"), default=params.fps),
                width=_as_int(output.get("width"), default=params.width),
                height=_as_int(output.get("height"), default=params.height),
                seed=_as_int(output.get("seed"), default=request.seed),
                source_image=request.source_image,
                source_image_urls=list(request.source_image_urls),
            )

        b64 = output.get("b64") or output.get("video_base64")
        if isinstance(b64, str) and b64.strip():
            return VideoResult(
                prompt=request.prompt,
                b64=b64.strip(),
                duration_seconds=params.duration,
                fps=params.fps,
                width=params.width,
                height=params.height,
                source_image=request.source_image,
                source_image_urls=list(request.source_image_urls),
                seed=request.seed,
            )

        raise RunPodOutputError(
            f"RunPod video job {job_id!r} completed without a usable url/b64",
            job_id=job_id,
            payload=dict(payload),
        )


def _as_float(value: object, *, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object, *, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
