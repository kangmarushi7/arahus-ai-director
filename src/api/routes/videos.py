"""Scene video generation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_progress_hub, get_project_service
from src.api.schemas import SceneActionRequest, SceneMediaResponse
from src.api.services.projects import ProjectService, video_generator_fn
from src.api.websocket.hub import ProgressHub
from src.studio.models import SceneLifecycle
from src.video.exceptions import VideoProviderError

router = APIRouter(tags=["videos"])


@router.post("/scene/{scene_id}/video", response_model=SceneMediaResponse)
async def generate_scene_video(
    scene_id: int,
    body: SceneActionRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    hub: Annotated[ProgressHub, Depends(get_progress_hub)],
) -> SceneMediaResponse:
    """Generate (or dry-run estimate) a video for one scene via StoryboardStudio."""
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

    if scene.status == SceneLifecycle.IMAGE_GENERATED:
        board = projects.studio.approve_image(board, scene_id, persist=True)

    memory = projects.memory_store.load(body.project_id)
    if memory is None:
        from src.models.memory import ProjectMemory

        record = projects.require(body.project_id)
        memory = ProjectMemory(project_id=body.project_id, topic=record.topic)

    await hub.publish(
        body.project_id,
        {
            "type": "video_start",
            "message": f"Generating video for scene {scene_id}",
            "payload": {"scene_id": scene_id},
        },
    )

    try:
        result = projects.studio.execute(
            board,
            scene_id=scene_id,
            media="videos",
            video_generator=None if body.dry_run else video_generator_fn,
            project_memory=memory,
            dry_run=body.dry_run,
            persist=not body.dry_run,
        )
    except VideoProviderError as exc:
        await hub.publish(
            body.project_id,
            {
                "type": "error",
                "message": str(exc),
                "payload": {"scene_id": scene_id, "media": "video"},
            },
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not body.dry_run and memory is not None:
        try:
            projects.memory_store.save(memory)
        except Exception:  # noqa: BLE001
            pass

    # Surface provider errors captured inside execute.
    if result.errors.get(str(scene_id)):
        detail = result.errors[str(scene_id)]
        await hub.publish(
            body.project_id,
            {
                "type": "error",
                "message": detail,
                "payload": {"scene_id": scene_id, "media": "video"},
            },
        )
        raise HTTPException(status_code=503, detail=detail)

    scene_out = result.storyboard.scene_by_id(scene_id)
    estimate = result.plan.estimate.to_dict() if result.plan.estimate else None
    url = scene_out.video.url if scene_out.video else None

    await hub.publish(
        body.project_id,
        {
            "type": "video_complete" if not body.dry_run else "video_estimate",
            "message": f"Scene {scene_id} video "
            + ("estimated" if body.dry_run else "ready"),
            "payload": {
                "scene_id": scene_id,
                "url": url,
                "asset_id": scene_out.video_asset_id,
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
        asset_id=scene_out.video_asset_id,
        estimate=estimate,
        storyboard_scene=scene_out.to_dict(),
    )
