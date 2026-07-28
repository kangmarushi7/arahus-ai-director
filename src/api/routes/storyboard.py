"""Storyboard REST routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_project_service, get_studio
from src.api.schemas import ScenePatchRequest, SceneReorderRequest
from src.api.services.projects import ProjectService
from src.studio.models import SceneLifecycle
from src.studio.service import StoryboardStudio
from src.studio.transitions import TransitionError

router = APIRouter(tags=["storyboard"])


@router.get("/projects/{project_id}/storyboard")
def get_storyboard(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[StoryboardStudio, Depends(get_studio)],
) -> dict[str, Any]:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    board = studio.load(project_id)
    if board is None:
        raise HTTPException(
            status_code=404,
            detail=f"No storyboard for project {project_id!r}. Run generate first.",
        )
    return board.to_dict()


@router.put("/projects/{project_id}/storyboard/order")
def reorder_storyboard(
    project_id: str,
    body: SceneReorderRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    studio: Annotated[StoryboardStudio, Depends(get_studio)],
) -> dict[str, Any]:
    """Persist drag-and-drop scene ordering for the Interactive Studio canvas."""
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    board = studio.load(project_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    try:
        board = studio.reorder_scenes(board, body.scene_ids, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return board.to_dict()


@router.patch("/storyboard/{scene_id}")
def patch_scene(
    scene_id: int,
    body: ScenePatchRequest,
    studio: Annotated[StoryboardStudio, Depends(get_studio)],
    projects: Annotated[ProjectService, Depends(get_project_service)],
    project_id: str = Query(..., description="Owning project id"),
) -> dict[str, Any]:
    """Patch a scene card (title, prompt, camera, status, …)."""
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    board = studio.load(project_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    try:
        scene = board.scene_by_id(scene_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    updates = body.model_dump(exclude_none=True)
    status_raw = updates.pop("status", None)
    continuity = updates.pop("continuity", None)
    if continuity is not None and scene.scene_plan is not None:
        updates["scene_plan"] = scene.scene_plan.model_copy(
            update={"continuity": continuity}
        )
    if updates:
        board = studio._commit_scene(
            board,
            scene_id,
            status=scene.status,
            change_summary="api patch",
            extra_updates=updates,
            persist=False,
            force_status=True,
        )
        scene = board.scene_by_id(scene_id)
    if status_raw is not None:
        try:
            target = SceneLifecycle(status_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status {status_raw!r}",
            ) from exc
        try:
            board = studio.transition_scene(
                board,
                scene_id,
                target,
                change_summary=f"api status → {target.value}",
                persist=False,
            )
        except TransitionError as exc:
            # Allow explicit regenerate-style rollbacks via force commit.
            board = studio._commit_scene(
                board,
                scene_id,
                status=target,
                change_summary=f"api force status → {target.value}",
                persist=False,
                force_status=True,
            )
            _ = exc
    board = studio.save(board)
    return board.scene_by_id(scene_id).to_dict()
