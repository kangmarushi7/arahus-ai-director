"""FastAPI dependency injection for the Arahus API."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from src.api.services.projects import ProjectService
from src.api.websocket.hub import ProgressHub, progress_hub
from src.audio.router import reset_audio_router_singleton
from src.audio.service import AudioStudioService
from src.audio.store import AudioProjectStore
from src.config import AppConfig, get_settings
from src.copilot.service import CopilotService
from src.export.service import ExportStudioService
from src.export.store import ExportStore
from src.memory.store import ProjectMemoryStore
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore
from src.timeline.service import TimelineService
from src.timeline.store import TimelineStore


@lru_cache(maxsize=1)
def get_projects_root() -> Path:
    return Path("artifacts") / "projects"


@lru_cache(maxsize=1)
def get_project_service() -> ProjectService:
    root = get_projects_root()
    return ProjectService(
        root=root,
        studio=StoryboardStudio(store=StoryboardStore(root=root)),
        memory_store=ProjectMemoryStore(root=root),
    )


@lru_cache(maxsize=1)
def get_copilot_service() -> CopilotService:
    projects = get_project_service()
    return CopilotService(
        root=get_projects_root(),
        studio=projects.studio,
        memory_store=projects.memory_store,
    )


@lru_cache(maxsize=1)
def get_timeline_service() -> TimelineService:
    return TimelineService(store=TimelineStore(root=get_projects_root()))


@lru_cache(maxsize=1)
def get_audio_studio() -> AudioStudioService:
    return AudioStudioService(
        root=get_projects_root(),
        store=AudioProjectStore(root=get_projects_root()),
        timeline_service=get_timeline_service(),
    )


@lru_cache(maxsize=1)
def get_export_studio() -> ExportStudioService:
    projects = get_project_service()
    root = get_projects_root()

    def _project(project_id: str) -> dict:
        try:
            return projects.to_response(projects.require(project_id))
        except KeyError:
            return {"id": project_id}

    def _storyboard(project_id: str) -> dict | None:
        board = projects.studio.load(project_id)
        return board.to_dict() if board else None

    def _memory(project_id: str) -> dict | None:
        memory = projects.memory_store.load(project_id)
        return memory.to_dict() if memory else None

    return ExportStudioService(
        root=root,
        store=ExportStore(root=root),
        timeline_service=get_timeline_service(),
        audio_service=get_audio_studio(),
        project_loader=_project,
        storyboard_loader=_storyboard,
        memory_loader=_memory,
    )


def get_app_settings() -> AppConfig:
    return get_settings()


def get_studio(
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> StoryboardStudio:
    return projects.studio


def get_memory_store(
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectMemoryStore:
    return projects.memory_store


def get_progress_hub(request: Request) -> ProgressHub:
    hub = getattr(request.app.state, "progress_hub", None)
    return hub or progress_hub


def reset_api_singletons() -> None:
    """Clear cached DI singletons (tests)."""
    get_projects_root.cache_clear()
    get_project_service.cache_clear()
    get_copilot_service.cache_clear()
    get_timeline_service.cache_clear()
    get_audio_studio.cache_clear()
    get_export_studio.cache_clear()
    reset_audio_router_singleton()
