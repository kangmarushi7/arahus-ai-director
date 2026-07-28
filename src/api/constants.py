"""Shared API path constants for the production FastAPI app."""

from __future__ import annotations

# Browser-facing prefix used when Studio and API share one origin (Railway).
# FastAPI itself still serves routes at the root; Caddy strips this prefix.
PUBLIC_API_PREFIX = "/backend"
