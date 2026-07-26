"""RunPod Serverless HTTP client for asynchronous image generation.

Talks to the RunPod ``/run`` and ``/status`` REST API with ``requests``.
Credentials and endpoint settings come from :class:`~src.config.ImageConfig`
via :meth:`RunPodClient.from_config`; callers may also inject values directly
for tests.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

import requests

from src.config import ImageConfig, get_settings
from src.models.image import ImageResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.runpod.ai/v2"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})
_FAILURE_STATUSES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})
_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class RunPodClientError(Exception):
    """Base error for failures inside :class:`RunPodClient`."""


class RunPodRequestError(RunPodClientError):
    """Raised when an HTTP request to RunPod fails after retries."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RunPodTimeoutError(RunPodClientError):
    """Raised when polling exceeds the configured timeout."""

    def __init__(self, message: str, *, job_id: str) -> None:
        super().__init__(message)
        self.job_id = job_id


class RunPodJobError(RunPodClientError):
    """Raised when a RunPod job ends in a non-success terminal state."""

    def __init__(
        self,
        message: str,
        *,
        job_id: str,
        status: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status = status
        self.payload = dict(payload) if payload is not None else None


class RunPodOutputError(RunPodClientError):
    """Raised when a completed job payload cannot be mapped to an image."""

    def __init__(
        self,
        message: str,
        *,
        job_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.payload = dict(payload) if payload is not None else None


class RunPodClient:
    """Thin RunPod Serverless client: submit → poll → parse → :class:`ImageResult`.

    Transport concerns only. Pipeline/orchestration logic stays outside this
    class. Dependencies (API key, endpoint, base URL, timeouts, session) are
    injected through the constructor or :meth:`from_config`.
    """

    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        """Configure the RunPod HTTP client.

        Args:
            api_key: RunPod API key (Bearer token).
            endpoint_id: Serverless endpoint identifier.
            base_url: RunPod API root, e.g. ``https://api.runpod.ai/v2``.
            request_timeout_seconds: Per-request socket timeout for submit/status.
            poll_interval_seconds: Delay between status polls.
            poll_timeout_seconds: Maximum wall time spent waiting for a job.
            max_retries: Attempts for transient network/HTTP failures (including
                the first try). Values below ``1`` are treated as ``1``.
            retry_backoff_seconds: Base linear backoff between HTTP retries.
            session: Optional shared :class:`requests.Session` for connection
                pooling and tests.

        Raises:
            ValueError: If required credentials or timeouts are invalid.
        """
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not endpoint_id.strip():
            raise ValueError("endpoint_id must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if poll_timeout_seconds <= 0:
            raise ValueError("poll_timeout_seconds must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")

        self.api_key = api_key.strip()
        self.endpoint_id = endpoint_id.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.poll_timeout_seconds = float(poll_timeout_seconds)
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self._session = session or requests.Session()
        self._owns_session = session is None

    @classmethod
    def from_config(
        cls,
        config: ImageConfig | None = None,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        session: requests.Session | None = None,
    ) -> RunPodClient:
        """Build a client from :class:`~src.config.ImageConfig`.

        Args:
            config: Image settings section. When omitted, loads via
                :func:`~src.config.get_settings`.
            request_timeout_seconds: Per-request socket timeout.
            poll_interval_seconds: Delay between status polls.
            poll_timeout_seconds: Maximum wall time spent waiting for a job.
            max_retries: Attempts for transient network/HTTP failures.
            retry_backoff_seconds: Base linear backoff between HTTP retries.
            session: Optional shared :class:`requests.Session`.

        Returns:
            A configured :class:`RunPodClient`.

        Raises:
            RuntimeError: If ``RUNPOD_API_KEY`` or ``RUNPOD_ENDPOINT_ID`` is missing.
        """
        image = config if config is not None else get_settings().image
        api_key, endpoint_id = image.require_credentials()
        return cls(
            api_key=api_key,
            endpoint_id=endpoint_id,
            base_url=image.base_url or DEFAULT_BASE_URL,
            request_timeout_seconds=request_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            session=session,
        )

    def close(self) -> None:
        """Close the underlying session when this client owns it."""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> RunPodClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def _run_url(self) -> str:
        return f"{self.base_url}/{self.endpoint_id}/run"

    def _status_url(self, job_id: str) -> str:
        return f"{self.base_url}/{self.endpoint_id}/status/{job_id}"

    def submit(self, prompt: str) -> str:
        """Enqueue an asynchronous image job and return its ``job_id``.

        Args:
            prompt: Text prompt describing the image to generate.

        Returns:
            The RunPod job identifier.

        Raises:
            ValueError: If ``prompt`` is empty.
            RunPodRequestError: If the submit request fails after retries.
            RunPodClientError: If the response does not include a job id.
        """
        cleaned = self._require_prompt(prompt)
        payload = {"input": {"prompt": cleaned, "num_images": 1}}
        logger.info(
            "event=runpod_submit endpoint_id=%s prompt_chars=%s",
            self.endpoint_id,
            len(cleaned),
        )
        response = self._request_json("POST", self._run_url, json_body=payload)
        job_id = response.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise RunPodClientError(
                f"RunPod submit response missing job id: {response!r}"
            )
        logger.info(
            "event=runpod_submitted endpoint_id=%s job_id=%s status=%r",
            self.endpoint_id,
            job_id,
            response.get("status"),
        )
        return job_id.strip()

    def poll(self, job_id: str) -> dict[str, Any]:
        """Poll job status until ``COMPLETED`` or a failure terminal state.

        Args:
            job_id: Identifier returned by :meth:`submit`.

        Returns:
            The final status payload as a dictionary.

        Raises:
            ValueError: If ``job_id`` is empty.
            RunPodTimeoutError: If the job does not finish in time.
            RunPodJobError: If the job ends in ``FAILED`` / ``CANCELLED`` /
                ``TIMED_OUT``.
            RunPodRequestError: If status requests fail after retries.
        """
        cleaned_id = job_id.strip()
        if not cleaned_id:
            raise ValueError("job_id must be a non-empty string")

        deadline = time.monotonic() + self.poll_timeout_seconds
        url = self._status_url(cleaned_id)
        logger.info(
            "event=runpod_poll_start job_id=%s timeout_seconds=%s",
            cleaned_id,
            self.poll_timeout_seconds,
        )

        while True:
            payload = self._request_json("GET", url)
            status = str(payload.get("status") or "").upper()
            logger.debug(
                "event=runpod_poll_tick job_id=%s status=%s",
                cleaned_id,
                status,
            )

            if status in _TERMINAL_STATUSES:
                if status in _FAILURE_STATUSES:
                    error_detail = payload.get("error") or payload.get("output")
                    raise RunPodJobError(
                        f"RunPod job {cleaned_id!r} ended with status "
                        f"{status}: {error_detail!r}",
                        job_id=cleaned_id,
                        status=status,
                        payload=payload,
                    )
                logger.info(
                    "event=runpod_poll_complete job_id=%s status=%s",
                    cleaned_id,
                    status,
                )
                return payload

            if time.monotonic() >= deadline:
                raise RunPodTimeoutError(
                    f"Timed out after {self.poll_timeout_seconds:.0f}s waiting "
                    f"for RunPod job {cleaned_id!r} (last status={status or 'unknown'})",
                    job_id=cleaned_id,
                )

            time.sleep(self.poll_interval_seconds)

    def generate(self, prompt: str) -> ImageResult:
        """Submit a prompt, wait for completion, and return an :class:`ImageResult`.

        Workflow:
            1. :meth:`submit`
            2. :meth:`poll`
            3. Parse the completed output
            4. Return :class:`~src.models.image.ImageResult`

        Args:
            prompt: Text prompt describing the image to generate.

        Returns:
            Parsed image result for the completed job.

        Raises:
            ValueError: If ``prompt`` is empty.
            RunPodTimeoutError: If polling times out.
            RunPodJobError: If the job fails on RunPod.
            RunPodOutputError: If the completed payload has no usable image.
            RunPodRequestError: If HTTP calls fail after retries.
        """
        cleaned = self._require_prompt(prompt)
        job_id = self.submit(cleaned)
        payload = self.poll(job_id)
        return self._parse_image_result(cleaned, job_id=job_id, payload=payload)

    def _require_prompt(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        return " ".join(prompt.split())

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an HTTP call with retries for transient failures."""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=dict(json_body) if json_body is not None else None,
                    timeout=self.request_timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = RunPodRequestError(
                    f"RunPod request timed out ({method} {url}): {exc}"
                )
            except requests.RequestException as exc:
                last_error = RunPodRequestError(
                    f"RunPod network error ({method} {url}): {exc}"
                )
            else:
                if response.status_code in _RETRYABLE_HTTP_STATUS:
                    last_error = RunPodRequestError(
                        f"RunPod returned retryable HTTP "
                        f"{response.status_code} for {method} {url}: "
                        f"{response.text[:500]}",
                        status_code=response.status_code,
                        response_body=_safe_json_or_text(response),
                    )
                elif response.status_code >= 400:
                    body = _safe_json_or_text(response)
                    raise RunPodRequestError(
                        f"RunPod request failed with HTTP "
                        f"{response.status_code} for {method} {url}: "
                        f"{response.text[:500]}",
                        status_code=response.status_code,
                        response_body=body,
                    )
                else:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise RunPodRequestError(
                            f"RunPod returned non-JSON for {method} {url}: "
                            f"{response.text[:500]}",
                            status_code=response.status_code,
                            response_body=response.text[:500],
                        ) from exc
                    if not isinstance(data, dict):
                        raise RunPodRequestError(
                            f"RunPod returned a non-object JSON payload for "
                            f"{method} {url}: {type(data).__name__}",
                            status_code=response.status_code,
                            response_body=data,
                        )
                    return data

            if attempt >= self.max_retries:
                break

            delay = self.retry_backoff_seconds * attempt
            logger.warning(
                "event=runpod_http_retry method=%s url=%s attempt=%s/%s "
                "delay_seconds=%.2f error=%s",
                method,
                url,
                attempt,
                self.max_retries,
                delay,
                last_error,
            )
            if delay > 0:
                time.sleep(delay)

        assert last_error is not None
        raise last_error

    def _parse_image_result(
        self,
        prompt: str,
        *,
        job_id: str,
        payload: Mapping[str, Any],
    ) -> ImageResult:
        """Map a completed RunPod status payload onto :class:`ImageResult`."""
        output = payload.get("output")
        url: str | None = None
        b64: str | None = None
        width: int | None = None
        height: int | None = None
        seed: int | None = None

        if isinstance(output, dict):
            url = _first_url(output)
            b64 = _first_b64(output)
            width = _optional_positive_int(output.get("width"))
            height = _optional_positive_int(output.get("height"))
            seed = _optional_int(output.get("seed"))
            # Worker (handler.py) returns {"images": [<public url>, ...]}.
            if url is None:
                images = output.get("images")
                if isinstance(images, list) and images:
                    first = images[0]
                    if isinstance(first, str) and first.strip():
                        url = first.strip()
                    elif isinstance(first, dict):
                        url = _first_url(first)
                        b64 = b64 or _first_b64(first)
        elif isinstance(output, list) and output:
            first = output[0]
            if isinstance(first, str) and first.strip():
                url = first.strip()
            elif isinstance(first, dict):
                url = _first_url(first)
                b64 = _first_b64(first)
                width = _optional_positive_int(first.get("width"))
                height = _optional_positive_int(first.get("height"))
                seed = _optional_int(first.get("seed"))
        elif isinstance(output, str) and output.strip():
            candidate = output.strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                url = candidate
            else:
                b64 = candidate

        if not url and not b64:
            raise RunPodOutputError(
                f"RunPod job {job_id!r} completed without an image URL or "
                f"base64 payload: {output!r}",
                job_id=job_id,
                payload=dict(payload),
            )

        return ImageResult(
            prompt=prompt,
            url=url,
            b64=b64,
            width=width,
            height=height,
            seed=seed,
        )


def _safe_json_or_text(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def _first_url(data: Mapping[str, Any]) -> str | None:
    for key in ("url", "image_url", "imageUrl"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_b64(data: Mapping[str, Any]) -> str | None:
    for key in ("b64", "image_b64", "image", "imageBase64"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = value.strip()
            # Skip obvious URLs stored under an image key.
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                continue
            if cleaned.startswith("data:") and "," in cleaned:
                return cleaned.split(",", 1)[1]
            return cleaned
    return None


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
