"""Cost and GPU-time estimation for pending studio generations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.studio.models import CostEstimate, SceneLifecycle, Storyboard, StoryboardScene

# Architecture defaults when router YAML is unavailable.
_DEFAULT_COST_PER_IMAGE = 0.02
_DEFAULT_COST_PER_VIDEO_SECOND = 0.05
_DEFAULT_IMAGE_GPU_SECONDS = 20.0
_DEFAULT_VIDEO_GPU_FACTOR = 12.0  # wall/GPU seconds per second of video


def _load_image_cost() -> float:
    try:
        from src.image.config import load_image_config

        config = load_image_config()
        model = next(iter(config.models.values()), None)
        if model is not None and model.cost_per_image > 0:
            return float(model.cost_per_image)
    except Exception:  # noqa: BLE001 - estimation must not fail hard
        pass
    return _DEFAULT_COST_PER_IMAGE


def _load_video_cost_per_second() -> float:
    try:
        from src.video.config import load_video_config

        config = load_video_config()
        model = next(iter(config.models.values()), None)
        if model is not None and model.cost_per_second > 0:
            return float(model.cost_per_second)
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_COST_PER_VIDEO_SECOND


def scenes_needing_images(scenes: Sequence[StoryboardScene]) -> list[StoryboardScene]:
    """Scenes approved for image work that do not yet have a successful image."""
    ready = {
        SceneLifecycle.APPROVED,
        SceneLifecycle.IMAGE_GENERATED,  # allow retry if error set
    }
    result: list[StoryboardScene] = []
    for scene in scenes:
        if scene.is_locked:
            continue
        if scene.status == SceneLifecycle.APPROVED:
            result.append(scene)
        elif scene.status == SceneLifecycle.IMAGE_GENERATED and scene.is_failed:
            result.append(scene)
        elif scene.status in ready and scene.image is None:
            result.append(scene)
    return result


def scenes_needing_videos(scenes: Sequence[StoryboardScene]) -> list[StoryboardScene]:
    """Scenes with approved images ready for video (or failed video retry)."""
    result: list[StoryboardScene] = []
    for scene in scenes:
        if scene.is_locked:
            continue
        if scene.status == SceneLifecycle.IMAGE_APPROVED:
            result.append(scene)
        elif scene.status == SceneLifecycle.VIDEO_GENERATED and scene.is_failed:
            result.append(scene)
    return result


def estimate_generation_cost(
    storyboard: Storyboard,
    *,
    scene_ids: Sequence[int] | None = None,
    media: str = "both",
    cost_per_image: float | None = None,
    cost_per_video_second: float | None = None,
    image_gpu_seconds: float = _DEFAULT_IMAGE_GPU_SECONDS,
    video_gpu_factor: float = _DEFAULT_VIDEO_GPU_FACTOR,
) -> CostEstimate:
    """Estimate USD cost and GPU time for pending generations.

    Args:
        storyboard: Studio storyboard document.
        scene_ids: Optional subset; defaults to all scenes.
        media: ``images``, ``videos``, or ``both``.
        cost_per_image: Override registry image cost.
        cost_per_video_second: Override registry video cost.
        image_gpu_seconds: Assumed GPU seconds per image.
        video_gpu_factor: Assumed GPU seconds per second of output video.
    """
    selected = list(storyboard.scenes)
    if scene_ids is not None:
        wanted = {int(item) for item in scene_ids}
        selected = [scene for scene in selected if scene.id in wanted]

    media_key = media.strip().lower()
    if media_key not in {"images", "videos", "both"}:
        raise ValueError("media must be 'images', 'videos', or 'both'")

    image_cost = (
        float(cost_per_image) if cost_per_image is not None else _load_image_cost()
    )
    video_cps = (
        float(cost_per_video_second)
        if cost_per_video_second is not None
        else _load_video_cost_per_second()
    )

    image_scenes = (
        scenes_needing_images(selected) if media_key in {"images", "both"} else []
    )
    video_scenes = (
        scenes_needing_videos(selected) if media_key in {"videos", "both"} else []
    )

    video_duration = sum(float(scene.duration_seconds) for scene in video_scenes)
    image_count = len(image_scenes)
    video_count = len(video_scenes)

    image_cost_total = image_count * image_cost
    video_cost_total = video_duration * video_cps
    gpu_seconds = (image_count * image_gpu_seconds) + (video_duration * video_gpu_factor)

    scene_id_list = sorted(
        {scene.id for scene in image_scenes} | {scene.id for scene in video_scenes}
    )

    breakdown: dict[str, Any] = {
        "images": {
            "count": image_count,
            "scene_ids": [scene.id for scene in image_scenes],
            "unit_cost": image_cost,
            "total_cost": round(image_cost_total, 8),
            "gpu_seconds": round(image_count * image_gpu_seconds, 3),
        },
        "videos": {
            "count": video_count,
            "scene_ids": [scene.id for scene in video_scenes],
            "duration_seconds": round(video_duration, 3),
            "unit_cost_per_second": video_cps,
            "total_cost": round(video_cost_total, 8),
            "gpu_seconds": round(video_duration * video_gpu_factor, 3),
        },
    }

    return CostEstimate(
        image_count=image_count,
        video_count=video_count,
        scene_ids=scene_id_list,
        estimated_gpu_seconds=round(gpu_seconds, 3),
        estimated_cost_usd=round(image_cost_total + video_cost_total, 8),
        cost_per_image=image_cost,
        cost_per_video_second=video_cps,
        video_duration_seconds=round(video_duration, 3),
        breakdown=breakdown,
    )
