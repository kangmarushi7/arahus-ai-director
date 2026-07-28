"""API security helpers — API key auth and CORS policy."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_PUBLIC_PREFIXES = (
    "/health",
    "/api/status",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)


def parse_cors_origins(raw: str | None) -> list[str]:
    """Parse comma-separated CORS origins; empty → localhost studio defaults."""
    text = (raw or "").strip()
    if not text:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    if text == "*":
        return ["*"]
    return [part.strip() for part in text.split(",") if part.strip()]


def resolve_api_key() -> str:
    """Return configured API key (empty means auth disabled — local/dev)."""
    return (
        os.getenv("ARAHUS_API_KEY", "").strip()
        or os.getenv("API_KEY", "").strip()
    )


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_PREFIXES:
        return True
    return any(path.startswith(prefix + "/") for prefix in _PUBLIC_PREFIXES if prefix != "/")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer`` or ``X-API-Key`` when a key is set.

    When ``ARAHUS_API_KEY`` / ``API_KEY`` is empty, all requests pass (local
    development). WebSocket upgrades are not covered by this middleware —
    use query ``?api_key=`` on ``/ws/...`` instead (see websocket route).
    """

    def __init__(
        self,
        app,
        *,
        api_key: str | None = None,
        public_prefixes: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._api_key = (api_key if api_key is not None else resolve_api_key()).strip()
        self._public = tuple(public_prefixes) if public_prefixes is not None else _PUBLIC_PREFIXES

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        if not self._api_key:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/ws/") or is_public_path(path):
            return await call_next(request)

        provided = _extract_api_key(request)
        if provided and hmac.compare_digest(provided, self._api_key):
            return await call_next(request)

        logger.warning(
            "event=api_auth_rejected path=%s client=%s",
            path,
            request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — provide Authorization: Bearer <ARAHUS_API_KEY>"},
        )


def _extract_api_key(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    x_key = request.headers.get("x-api-key")
    if x_key:
        return x_key.strip()
    return None


def websocket_api_key_ok(websocket_query_api_key: str | None) -> bool:
    """Validate optional ``api_key`` query param for WebSocket connections."""
    expected = resolve_api_key()
    if not expected:
        return True
    provided = (websocket_query_api_key or "").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
