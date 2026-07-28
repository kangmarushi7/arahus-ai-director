"""Scene image generation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_progress_hub, get_project_service
from src.api.schemas import SceneActionRequest, SceneMediaResponse
from src.api.services.projects import ProjectService, image_generator_fn
from src.api.websocket.hub import ProgressHub
from src.studio.models import SceneLifecycle

router = APIRouter(tags=["images"])


@router.post("/scene/{scene_id}/image", response_model=SceneMediaResponse)
async def generate_scene_image(
    scene_id: int,
    body: SceneActionRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    hub: Annotated[ProgressHub, Depends(get_progress_hub)],
) -> SceneMediaResponse:
    """Generate (or dry-run estimate) an image for one scene via StoryboardStudio."""
    try:
        projects.require(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    board = projects.studio.load(body.project_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    try:
        scene = board.scene_by_id(scene_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if scene.status == SceneLifecycle.DRAFT:
        board = projects.studio.approve_scene(board, scene_id, persist=True)

    memory = projects.memory_store.load(body.project_id)
    if memory is None:
        from src.models.memory import ProjectMemory

        record = projects.require(body.project_id)
        memory = ProjectMemory(project_id=body.project_id, topic=record.topic)

    await hub.publish(
        body.project_id,
        {
            "type": "image_start",
            "message": f"Generating image for scene {scene_id}",
            "payload": {"scene_id": scene_id},
        },
    )

    result = projects.studio.execute(
        board,
        scene_id=scene_id,
        media="images",
        image_generator=None if body.dry_run else image_generator_fn,
        project_memory=memory,
        dry_run=body.dry_run,
        persist=not body.dry_run,
    )
    if not body.dry_run and memory is not None:
        try:
            projects.memory_store.save(memory)
        except Exception:  # noqa: BLE001 - best-effort
            pass

    scene_out = result.storyboard.scene_by_id(scene_id)
    estimate = result.plan.estimate.to_dict() if result.plan.estimate else None
    url = scene_out.image.url if scene_out.image else None

    await hub.publish(
        body.project_id,
        {
            "type": "image_complete" if not body.dry_run else "image_estimate",
            "message": f"Scene {scene_id} image "
            + ("estimated" if body.dry_run else "ready"),
            "payload": {
                "scene_id": scene_id,
                "url": url,
                "asset_id": scene_out.image_asset_id,
                "dry_run": body.dry_run,
            },
        },
    )

    return SceneMediaResponse(
        project_id=body.project_id,
        scene_id=scene_id,
        status=scene_out.status.value,
        dry_run=body.dry_run,
        url=url,
        asset_id=scene_out.image_asset_id,
        estimate=estimate,
        storyboard_scene=scene_out.to_dict(),
    )
