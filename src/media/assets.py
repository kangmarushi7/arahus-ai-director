"""AssetRegistry helpers for media outputs (image / video / future)."""

from __future__ import annotations

from typing import Any

from src.models.memory import AssetKind, AssetRecord, ProjectMemory


def register_scene_video(
    memory: ProjectMemory,
    *,
    scene_id: int,
    title: str = "",
    url: str | None = None,
    status: str = "ok",
    source_image_urls: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AssetRecord:
    """Register a scene video under the project :class:`AssetRegistry`.

    Slug form: ``scene_{id}_video``. Stable numeric IDs survive reloads when
    the same project memory is reused.
    """
    if scene_id < 1:
        raise ValueError("scene_id must be >= 1")
    registry = memory.registry
    if registry is None:
        raise ValueError("project memory has no asset registry")

    refs: dict[str, str] = {}
    if url:
        refs["url"] = url
    if source_image_urls:
        for index, source in enumerate(source_image_urls):
            if source:
                refs[f"source_image_{index}"] = source

    meta = {
        "scene_id": scene_id,
        "status": status,
        **(metadata or {}),
    }
    return registry.register(
        kind=AssetKind.VIDEO,
        slug=f"scene_{scene_id}_video",
        label=title or f"Scene {scene_id} video",
        refs=refs,
        metadata=meta,
    )
