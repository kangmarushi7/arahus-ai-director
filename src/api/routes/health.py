"""Health and readiness routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.api.schemas import HealthResponse
from src.webapp.serialize import config_status_payload

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Load-balancer / uptime probe."""
    return HealthResponse()


@router.get("/api/status")
def api_status() -> dict[str, Any]:
    """Integration readiness (LLM / RunPod / R2 / stubs)."""
    return config_status_payload()
