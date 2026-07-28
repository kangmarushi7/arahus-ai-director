"""FastAPI application factory for the Arahus production API."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import api_router
from src.api.websocket import progress_hub
from src.api.websocket.progress import router as websocket_router
from src.config import get_settings
from src.security import ApiKeyMiddleware

logger = logging.getLogger(__name__)


def create_app(*, enable_cors: bool = True) -> FastAPI:
    """Build the production FastAPI app (OpenAPI at ``/docs`` when enabled)."""
    settings = get_settings()
    docs_enabled = settings.security.docs_enabled
    application = FastAPI(
        title="Arahus API",
        description=(
            "Production REST + WebSocket API for Arahus AI Director. "
            "Wraps DirectorPipeline, Storyboard Studio, memory, and media "
            "engines without duplicating business logic."
        ),
        version="7.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.state.progress_hub = progress_hub

    # Auth first (outermost runs last in Starlette — add auth after CORS so
    # preflight OPTIONS still succeed, then API key is enforced on real calls).
    api_key = settings.security.resolved_api_key()
    if api_key:
        application.add_middleware(ApiKeyMiddleware, api_key=api_key)
        logger.info("event=api_auth_enabled")
    else:
        logger.warning(
            "event=api_auth_disabled detail=ARAHUS_API_KEY empty — local/dev only"
        )

    if enable_cors:
        origins = settings.security.resolved_cors_origins()
        allow_credentials = origins != ["*"]
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if settings.pipeline.allow_stub_services:
        logger.warning(
            "event=stub_services_enabled detail=ALLOW_STUB_SERVICES=true — "
            "do not use in production"
        )

    application.include_router(api_router)
    application.include_router(websocket_router)

    # Optional: mount lab admin under /api/admin when available.
    try:
        from src.webapp.admin import router as admin_router

        application.include_router(admin_router)
    except Exception:  # noqa: BLE001 - admin is optional
        pass

    return application


app = create_app()
