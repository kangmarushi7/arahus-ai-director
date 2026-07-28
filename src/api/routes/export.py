"""Project export + publishing routes (Sprint 6.6)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.deps import (
    get_export_studio,
    get_project_service,
    get_timeline_service,
)
from src.api.schemas import ExportResponse
from src.api.services.projects import ProjectService
from src.export.models import ExportFormat, ExportPresetId, PublishPlatform
from src.export.service import ExportStudioService
from src.timeline.service import TimelineService

router = APIRouter(tags=["export"])


class EnqueueExportRequest(BaseModel):
    preset: str = "youtube"
    format: str | None = None
    width: int | None = Field(default=None, ge=16)
    height: int | None = Field(default=None, ge=16)
    fps: int | None = Field(default=None, ge=1)
    aspect: str | None = None
    include_subtitles: bool = True
    include_audio: bool = True
    custom_label: str | None = None
    process: bool = True


class PublishRequest(BaseModel):
    render_job_id: str
    platform: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    schedule_at: str | None = None
    run: bool = True


def _require_project(project_id: str, projects: ProjectService) -> None:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _http_value_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/projects/{project_id}/export", response_model=ExportResponse)
def export_project(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> ExportResponse:
    """Export project metadata + storyboard + memory + timeline as JSON."""
    try:
        record = projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    board = projects.studio.load(project_id)
    memory = projects.memory_store.load(project_id)
    timeline_doc = timelines.load(project_id)
    project_payload: dict[str, Any] = projects.to_response(record)
    return ExportResponse(
        project_id=project_id,
        format="json",
        project=project_payload,
        storyboard=board.to_dict() if board else None,
        memory=memory.to_dict() if memory else None,
        timeline=timeline_doc.to_dict() if timeline_doc else None,
    )


@router.get("/export/presets")
def list_export_presets(
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    return {"presets": studio.presets()}


@router.get("/export/providers")
def list_publish_providers(
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    return {"providers": studio.provider_health()}


@router.get("/projects/{project_id}/exports")
def get_export_studio_state(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    return studio.get_or_create(project_id).to_dict()


@router.post("/projects/{project_id}/exports")
def enqueue_export(
    project_id: str,
    body: EnqueueExportRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        preset = ExportPresetId(body.preset)
        fmt = ExportFormat(body.format) if body.format else None
    except ValueError as exc:
        raise _http_value_error(exc) from exc
    try:
        state = studio.enqueue(
            project_id,
            preset=preset,
            format=fmt,
            width=body.width,
            height=body.height,
            fps=body.fps,
            aspect=body.aspect,
            include_subtitles=body.include_subtitles,
            include_audio=body.include_audio,
            custom_label=body.custom_label,
            process=body.process,
        )
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc
    return state.to_dict()


@router.post("/projects/{project_id}/exports/process")
def process_export_queue(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    return studio.process_queue(project_id).to_dict()


@router.post("/projects/{project_id}/exports/{job_id}/cancel")
def cancel_export_job(
    project_id: str,
    job_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.cancel(project_id, job_id).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc


@router.post("/projects/{project_id}/exports/{job_id}/pause")
def pause_export_job(
    project_id: str,
    job_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.pause(project_id, job_id).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc


@router.post("/projects/{project_id}/exports/{job_id}/resume")
def resume_export_job(
    project_id: str,
    job_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
    process: bool = Query(default=True),
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.resume(project_id, job_id, process=process).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc


@router.post("/projects/{project_id}/exports/{job_id}/retry")
def retry_export_job(
    project_id: str,
    job_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
    process: bool = Query(default=True),
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.retry(project_id, job_id, process=process).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc


@router.get("/projects/{project_id}/exports/history")
def export_history(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    state = studio.get_or_create(project_id)
    return {
        "project_id": project_id,
        "history": [h.model_dump(mode="json") for h in state.history],
    }


@router.post("/projects/{project_id}/publish")
def schedule_or_publish(
    project_id: str,
    body: PublishRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        platform = PublishPlatform(body.platform)
        state = studio.schedule_publish(
            project_id,
            render_job_id=body.render_job_id,
            platform=platform,
            title=body.title,
            description=body.description,
            tags=body.tags,
            schedule_at=body.schedule_at,
            run=body.run,
        )
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc
    return state.to_dict()


@router.post("/projects/{project_id}/publish/{publish_id}/run")
def run_publish_job(
    project_id: str,
    publish_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.run_publish(project_id, publish_id).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc


@router.post("/projects/{project_id}/publish/{publish_id}/cancel")
def cancel_publish_job(
    project_id: str,
    publish_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[ExportStudioService, Depends(get_export_studio)],
) -> dict[str, Any]:
    _require_project(project_id, projects)
    try:
        return studio.cancel_publish(project_id, publish_id).to_dict()
    except (KeyError, ValueError) as exc:
        raise _http_value_error(exc) from exc
