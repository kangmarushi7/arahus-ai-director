"""HTTP route aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.routes import (
    assets,
    audio,
    chat,
    export,
    health,
    images,
    projects,
    storyboard,
    timeline,
    videos,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(storyboard.router)
api_router.include_router(images.router)
api_router.include_router(videos.router)
api_router.include_router(assets.router)
api_router.include_router(chat.router)
api_router.include_router(timeline.router)
api_router.include_router(audio.router)
api_router.include_router(export.router)
