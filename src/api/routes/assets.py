"""Asset registry routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_project_service
from src.api.schemas import AssetItem, AssetListResponse
from src.api.services.projects import ProjectService

router = APIRouter(tags=["assets"])


@router.get("/assets", response_model=AssetListResponse)
def list_assets(
    projects: Annotated[ProjectService, Depends(get_project_service)],
    project_id: str | None = Query(
        default=None,
        description="When set, list assets for one project registry.",
    ),
) -> AssetListResponse:
    """List creative assets from ProjectMemory AssetRegistry."""
    if project_id:
        try:
            projects.require(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        memory = projects.memory_store.load(project_id)
        if memory is None or memory.registry is None:
            return AssetListResponse(project_id=project_id, assets=[], count=0)
        items = [
            AssetItem(
                id=record.id,
                kind=record.kind.value,
                slug=record.slug,
                label=record.label,
                refs=dict(record.refs),
                metadata=dict(record.metadata),
            )
            for record in memory.registry.assets.values()
        ]
        items.sort(key=lambda item: item.id)
        return AssetListResponse(project_id=project_id, assets=items, count=len(items))

    # Aggregate across projects.
    aggregated: list[AssetItem] = []
    for record in projects.list_projects():
        memory = projects.memory_store.load(record.id)
        if memory is None or memory.registry is None:
            continue
        for asset in memory.registry.assets.values():
            aggregated.append(
                AssetItem(
                    id=asset.id,
                    kind=asset.kind.value,
                    slug=asset.slug,
                    label=f"[{record.id}] {asset.label}",
                    refs=dict(asset.refs),
                    metadata={**asset.metadata, "project_id": record.id},
                )
            )
    return AssetListResponse(project_id=None, assets=aggregated, count=len(aggregated))
