"""Project REST routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from src.api.deps import get_progress_hub, get_project_service
from src.api.factory import build_pipeline
from src.api.schemas import (
    GenerateAcceptedResponse,
    GenerateRequest,
    GenerateSyncResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
)
from src.api.services.projects import ProjectService
from src.api.websocket.hub import ProgressHub
from src.pipeline import PipelineValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreateRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    """Create a project for a topic (idempotent for the same topic hash)."""
    try:
        record = projects.create(body.topic, project_id=body.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectResponse(**projects.to_response(record))


@router.get("", response_model=ProjectListResponse)
def list_projects(
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectListResponse:
    items = [
        ProjectResponse(**projects.to_response(record))
        for record in projects.list_projects()
    ]
    return ProjectListResponse(projects=items, count=len(items))


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    try:
        record = projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectResponse(**projects.to_response(record))


def _run_generate_job(
    *,
    project_id: str,
    topic: str,
    sync_studio: bool,
    projects: ProjectService,
    hub: ProgressHub,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Background worker: call DirectorPipeline.generate (unchanged API)."""
    callback = hub.make_progress_callback(loop, project_id)
    try:
        hub.publish_threadsafe(
            loop,
            project_id,
            {"type": "status", "message": "Generation started", "payload": {"status": "generating"}},
        )
        pipeline = build_pipeline()
        result = pipeline.generate(topic, progress_callback=callback)
        if sync_studio:
            projects.sync_studio_from_pipeline(result, project_id=project_id)
        record = projects.require(project_id)
        record.status = "ready"
        record.last_run_id = result.run_id
        projects.save(record)
        hub.publish_threadsafe(
            loop,
            project_id,
            {
                "type": "complete",
                "message": "Pipeline finished",
                "fraction": 1.0,
                "payload": {
                    "status": "ready",
                    "run_id": result.run_id,
                    "review_score": result.review.overall_score
                    if result.review
                    else None,
                    "scene_count": len(result.storyboard.scenes),
                },
            },
        )
    except PipelineValidationError as exc:
        _fail_project(projects, hub, loop, project_id, str(exc), review=exc.review)
    except Exception as exc:  # noqa: BLE001
        logger.exception("event=project_generate_failed project_id=%r", project_id)
        _fail_project(projects, hub, loop, project_id, str(exc))


def _fail_project(
    projects: ProjectService,
    hub: ProgressHub,
    loop: asyncio.AbstractEventLoop,
    project_id: str,
    error: str,
    *,
    review: Any = None,
) -> None:
    try:
        record = projects.require(project_id)
        record.status = "failed"
        projects.save(record)
    except Exception:  # noqa: BLE001
        pass
    payload: dict[str, Any] = {"status": "failed", "error": error}
    if review is not None:
        payload["review_score"] = getattr(review, "overall_score", None)
    hub.publish_threadsafe(
        loop,
        project_id,
        {"type": "error", "message": error, "payload": payload},
    )


@router.post("/{project_id}/generate")
async def generate_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    hub: Annotated[ProgressHub, Depends(get_progress_hub)],
    body: GenerateRequest | None = None,
    wait: bool = Query(
        default=False,
        description="When true, run synchronously and return the result body.",
    ),
) -> GenerateAcceptedResponse | GenerateSyncResponse:
    """Run ``DirectorPipeline.generate(topic)`` for the project.

    Default is async (202 + WebSocket progress). Pass ``wait=true`` for a
    synchronous response (useful in tests / simple clients).
    """
    try:
        record = projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    opts = body or GenerateRequest()
    record.status = "generating"
    projects.save(record)

    if wait:
        try:
            pipeline = build_pipeline()
            result = pipeline.generate(record.topic)
            if opts.sync_studio:
                projects.sync_studio_from_pipeline(result, project_id=project_id)
            record.status = "ready"
            record.last_run_id = result.run_id
            projects.save(record)
            board = projects.studio.load(project_id)
            return GenerateSyncResponse(
                project_id=project_id,
                topic=record.topic,
                status="ready",
                run_id=result.run_id,
                scene_count=len(result.storyboard.scenes),
                review_score=result.review.overall_score if result.review else None,
                storyboard=board.to_dict() if board else None,
                metrics=dict(result.metrics or {}),
            )
        except PipelineValidationError as exc:
            record.status = "failed"
            projects.save(record)
            raise HTTPException(
                status_code=422,
                detail=f"Storyboard rejected: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            projects.save(record)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    loop = asyncio.get_running_loop()
    background_tasks.add_task(
        _run_generate_job,
        project_id=project_id,
        topic=record.topic,
        sync_studio=opts.sync_studio,
        projects=projects,
        hub=hub,
        loop=loop,
    )
    return GenerateAcceptedResponse(
        project_id=project_id,
        topic=record.topic,
        status="generating",
        websocket_url=f"/ws/projects/{project_id}",
    )
