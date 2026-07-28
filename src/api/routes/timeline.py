"""Timeline editor REST routes — non-destructive, asset-reference only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_project_service, get_timeline_service
from src.api.schemas import (
    TimelineClipMoveRequest,
    TimelineClipResizeRequest,
    TimelineExportRequest,
    TimelineMergeRequest,
    TimelineReorderRequest,
    TimelineSeekRequest,
    TimelineSplitRequest,
    TimelineSyncRequest,
    TimelineTransitionRequest,
    TimelineTrimRequest,
)
from src.api.services.projects import ProjectService
from src.timeline.models import ExportAspect, ExportFormat, TransitionType
from src.timeline.service import TimelineService

router = APIRouter(tags=["timeline"])


def _require_timeline(
    project_id: str,
    projects: ProjectService,
    timelines: TimelineService,
    *,
    sync_if_missing: bool = True,
) -> Any:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    timeline = timelines.load(project_id)
    if timeline is None and sync_if_missing:
        board = projects.studio.load(project_id)
        timeline = timelines.get_or_create(project_id, storyboard=board)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return timeline


@router.get("/projects/{project_id}/timeline")
def get_timeline(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/sync")
def sync_timeline(
    project_id: str,
    body: TimelineSyncRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    board = projects.studio.load(project_id)
    if board is None:
        raise HTTPException(
            status_code=404,
            detail="Storyboard required to sync timeline",
        )
    timeline = timelines.sync_from_storyboard(
        project_id,
        board,
        preserve_non_video=body.preserve_non_video,
    )
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/move")
def move_clip(
    project_id: str,
    clip_id: str,
    body: TimelineClipMoveRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.move_clip(
            timeline,
            clip_id,
            start_seconds=body.start_seconds,
            track_id=body.track_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/resize")
def resize_clip(
    project_id: str,
    clip_id: str,
    body: TimelineClipResizeRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.resize_clip(
            timeline, clip_id, duration_seconds=body.duration_seconds
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.put("/projects/{project_id}/timeline/order")
def reorder_clips(
    project_id: str,
    body: TimelineReorderRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.reorder_clips(
            timeline, body.track_id, body.clip_ids
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/trim")
def trim_clip(
    project_id: str,
    clip_id: str,
    body: TimelineTrimRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.trim_clip(
            timeline,
            clip_id,
            in_point=body.in_point,
            out_point=body.out_point,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/split")
def split_clip(
    project_id: str,
    clip_id: str,
    body: TimelineSplitRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.split_clip(
            timeline, clip_id, at_seconds=body.at_seconds
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/merge")
def merge_clips(
    project_id: str,
    body: TimelineMergeRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.merge_clips(timeline, body.clip_ids)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.delete("/projects/{project_id}/timeline/clips/{clip_id}")
def delete_clip(
    project_id: str,
    clip_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
    close_gaps: bool = Query(default=False),
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.delete_clip(
            timeline, clip_id, close_gaps=close_gaps
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/duplicate")
def duplicate_clip(
    project_id: str,
    clip_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        timeline = timelines.duplicate_clip(timeline, clip_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/clips/{clip_id}/transition")
def set_transition(
    project_id: str,
    clip_id: str,
    body: TimelineTransitionRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    try:
        tin = (
            TransitionType(body.transition_in)
            if body.transition_in
            else None
        )
        tout = (
            TransitionType(body.transition_out)
            if body.transition_out
            else None
        )
        timeline = timelines.set_transition(
            timeline,
            clip_id,
            transition_in=tin,
            transition_out=tout,
            transition_duration=body.transition_duration,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return timeline.to_dict()


@router.post("/projects/{project_id}/timeline/seek")
def seek_timeline(
    project_id: str,
    body: TimelineSeekRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    timeline = timelines.seek(timeline, body.seconds)
    preview = timelines.preview_at(timeline)
    payload = timeline.to_dict()
    payload["preview"] = preview
    return payload


@router.get("/projects/{project_id}/timeline/preview")
def preview_timeline(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
    seconds: float | None = Query(default=None, ge=0.0),
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    return timelines.preview_at(timeline, seconds)


@router.post("/projects/{project_id}/timeline/export")
def enqueue_export(
    project_id: str,
    body: TimelineExportRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    timeline = _require_timeline(project_id, projects, timelines)
    timeline = timelines.enqueue_export(
        timeline,
        format=ExportFormat(body.format),
        aspect=ExportAspect(body.aspect),
    )
    return timeline.to_dict()
