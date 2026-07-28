"""Storyboard Studio service — approve, review, version, partial execute."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

from src.config import get_settings
from src.media.assets import register_scene_video
from src.models.image import ImageResult, VideoResult
from src.models.memory import AssetKind, ProjectMemory
from src.models.review import ReviewResult
from src.models.scene_plan import StoryPlan
from src.models.storyboard import DirectorPlan
from src.studio.builder import (
    build_from_director_plan,
    build_from_story_plan,
    to_pipeline_storyboard,
)
from src.studio.estimates import estimate_generation_cost
from src.studio.models import (
    CostEstimate,
    PartialExecutionPlan,
    PartialExecutionResult,
    RegenerateTarget,
    SceneLifecycle,
    Storyboard,
    StoryboardScene,
    _utc_iso,
)
from src.studio.selection import resolve_scene_ids
from src.studio.store import StoryboardStore
from src.studio.transitions import (
    TransitionError,
    assert_transition,
    rollback_for,
)

if TYPE_CHECKING:
    from src.agents.review import ReviewAgent
    from src.domain.models import DomainInfo

logger = logging.getLogger(__name__)

ImageGeneratorFn = Callable[[str], ImageResult]
VideoGeneratorFn = Callable[..., VideoResult]


class StoryboardStudio:
    """Persistent collaborative storyboard workflow.

    Does **not** change :meth:`DirectorPipeline.generate`. Studio is an
    additive workflow for approve → estimate → partial media generation.
    """

    def __init__(
        self,
        store: StoryboardStore | None = None,
        *,
        approval_threshold: float | None = None,
    ) -> None:
        self._store = store or StoryboardStore()
        if approval_threshold is None:
            self._approval_threshold = float(
                get_settings().pipeline.approval_threshold
            )
        else:
            self._approval_threshold = float(approval_threshold)

    @property
    def store(self) -> StoryboardStore:
        return self._store

    @property
    def approval_threshold(self) -> float:
        return self._approval_threshold

    # ------------------------------------------------------------------
    # Build / persist
    # ------------------------------------------------------------------

    def create_from_plan(
        self,
        plan: DirectorPlan | StoryPlan,
        *,
        project_id: str | None = None,
        characters: list[str] | None = None,
        persist: bool = True,
    ) -> Storyboard:
        """Create a draft studio storyboard from a director / story plan."""
        if isinstance(plan, StoryPlan):
            board = build_from_story_plan(
                plan, project_id=project_id, characters=characters
            )
        elif isinstance(plan, DirectorPlan):
            board = build_from_director_plan(
                plan, project_id=project_id, characters=characters
            )
        else:
            raise TypeError("plan must be a DirectorPlan or StoryPlan")

        # Seed version history with v1 snapshots.
        scenes = [
            scene.model_copy(
                update={
                    "versions": [scene.snapshot(change_summary="initial draft")],
                }
            )
            for scene in board.scenes
        ]
        board = board.model_copy(update={"scenes": scenes})
        if persist:
            self._store.save(board)
        return board

    def load(self, project_id: str) -> Storyboard | None:
        return self._store.load(project_id)

    def save(self, storyboard: Storyboard) -> Storyboard:
        board = storyboard.touch()
        self._store.save(board)
        return board

    def reorder_scenes(
        self,
        storyboard: Storyboard,
        scene_ids: list[int],
        *,
        persist: bool = True,
    ) -> Storyboard:
        """Reorder scenes by a full permutation of existing scene ids."""
        by_id = {scene.id: scene for scene in storyboard.scenes}
        if not scene_ids or set(scene_ids) != set(by_id):
            raise ValueError(
                "scene_ids must be a permutation of the storyboard's scene ids"
            )
        scenes = [by_id[scene_id] for scene_id in scene_ids]
        board = storyboard.model_copy(
            update={
                "scenes": scenes,
                "version": storyboard.version + 1,
                "updated_at": _utc_iso(),
            }
        )
        if persist:
            return self.save(board)
        return board.touch()

    # ------------------------------------------------------------------
    # Lifecycle / versioning
    # ------------------------------------------------------------------

    def transition_scene(
        self,
        storyboard: Storyboard,
        scene_id: int,
        target: SceneLifecycle,
        *,
        change_summary: str = "",
        persist: bool = True,
        clear_error: bool = True,
    ) -> Storyboard:
        """Advance (or no-op) a scene status and append version history."""
        scene = storyboard.scene_by_id(scene_id)
        if scene.is_locked and target != SceneLifecycle.LOCKED:
            raise TransitionError(
                f"Scene {scene_id} is locked",
                current=scene.status,
                target=target,
            )
        assert_transition(scene.status, target)
        return self._commit_scene(
            storyboard,
            scene_id,
            status=target,
            change_summary=change_summary or f"status → {target.value}",
            clear_error=clear_error,
            persist=persist,
        )

    def approve_scene(
        self,
        storyboard: Storyboard,
        scene_id: int,
        *,
        persist: bool = True,
    ) -> Storyboard:
        """Mark a draft scene approved for media generation."""
        return self.transition_scene(
            storyboard,
            scene_id,
            SceneLifecycle.APPROVED,
            change_summary="scene approved",
            persist=persist,
        )

    def approve_image(
        self,
        storyboard: Storyboard,
        scene_id: int,
        *,
        persist: bool = True,
    ) -> Storyboard:
        return self.transition_scene(
            storyboard,
            scene_id,
            SceneLifecycle.IMAGE_APPROVED,
            change_summary="image approved",
            persist=persist,
        )

    def approve_video(
        self,
        storyboard: Storyboard,
        scene_id: int,
        *,
        persist: bool = True,
    ) -> Storyboard:
        return self.transition_scene(
            storyboard,
            scene_id,
            SceneLifecycle.VIDEO_APPROVED,
            change_summary="video approved",
            persist=persist,
        )

    def lock_scene(
        self,
        storyboard: Storyboard,
        scene_id: int,
        *,
        persist: bool = True,
    ) -> Storyboard:
        return self.transition_scene(
            storyboard,
            scene_id,
            SceneLifecycle.LOCKED,
            change_summary="scene locked",
            persist=persist,
        )

    def regenerate(
        self,
        storyboard: Storyboard,
        scene_id: int,
        target: RegenerateTarget,
        *,
        persist: bool = True,
        updates: dict[str, Any] | None = None,
    ) -> Storyboard:
        """Regenerate camera / prompt / image / video without wiping the board.

        Rolls the scene back to the appropriate lifecycle status and bumps
        version history. Does not call GPU providers — callers re-run
        :meth:`execute` for media targets.
        """
        scene = storyboard.scene_by_id(scene_id)
        if scene.is_locked:
            raise TransitionError(
                f"Scene {scene_id} is locked",
                current=scene.status,
            )
        new_status = rollback_for(target)
        patch: dict[str, Any] = dict(updates or {})
        if target in {"image", "video"}:
            if target == "image":
                patch.setdefault("image", None)
                patch.setdefault("image_asset_id", None)
            if target == "video":
                patch.setdefault("video", None)
                patch.setdefault("video_asset_id", None)
        if target in {"camera", "prompt", "scene"}:
            patch.setdefault("image", None)
            patch.setdefault("video", None)
            patch.setdefault("image_asset_id", None)
            patch.setdefault("video_asset_id", None)

        return self._commit_scene(
            storyboard,
            scene_id,
            status=new_status,
            change_summary=f"regenerate {target}",
            extra_updates=patch,
            clear_error=True,
            persist=persist,
            force_status=True,
        )

    # ------------------------------------------------------------------
    # Review (before GPU)
    # ------------------------------------------------------------------

    def review(
        self,
        storyboard: Storyboard,
        review_agent: ReviewAgent,
        *,
        domain_info: DomainInfo | None = None,
        auto_approve: bool = True,
        persist: bool = True,
    ) -> tuple[Storyboard, ReviewResult]:
        """Run :class:`ReviewAgent` before any media generation.

        When ``auto_approve`` is True and the review passes the configured
        threshold, draft scenes are transitioned to ``approved``.
        """
        pipeline_board = to_pipeline_storyboard(storyboard)
        result = review_agent.run(pipeline_board, domain_info=domain_info)
        # Enforce local threshold (ReviewAgent also applies settings threshold).
        approved = bool(result.overall_score >= self._approval_threshold)
        result = result.model_copy(update={"approved": approved})

        board = storyboard.model_copy(
            update={"review": result, "updated_at": _utc_iso()}
        )
        scene_updates: list[StoryboardScene] = []
        for scene in board.scenes:
            updated = scene.model_copy(update={"review": result})
            if (
                auto_approve
                and approved
                and scene.status == SceneLifecycle.DRAFT
                and not scene.is_locked
            ):
                snap = updated.snapshot(change_summary="approved by review")
                versions = list(updated.versions) + [snap]
                updated = updated.model_copy(
                    update={
                        "status": SceneLifecycle.APPROVED,
                        "version": updated.version + 1,
                        "versions": versions,
                        "updated_at": _utc_iso(),
                        "error": None,
                    }
                )
            scene_updates.append(updated)
        board = board.model_copy(update={"scenes": scene_updates})
        if approved:
            board = board.model_copy(update={"status": SceneLifecycle.APPROVED})
        if persist:
            board = self.save(board)
        logger.info(
            "event=studio_review_complete project_id=%r score=%.1f approved=%s",
            board.project_id,
            result.overall_score,
            approved,
        )
        return board, result

    # ------------------------------------------------------------------
    # Cost estimation + partial execution
    # ------------------------------------------------------------------

    def estimate(
        self,
        storyboard: Storyboard,
        *,
        scene_id: int | None = None,
        scene_ids: Sequence[int] | None = None,
        scene_range: tuple[int, int] | None = None,
        media: Literal["images", "videos", "both"] = "both",
        retry_failed: bool = False,
    ) -> CostEstimate:
        """Estimate cost/GPU time for a pending partial generation."""
        ids = resolve_scene_ids(
            storyboard,
            scene_id=scene_id,
            scene_ids=scene_ids,
            scene_range=scene_range,
            retry_failed=retry_failed,
        )
        return estimate_generation_cost(
            storyboard,
            scene_ids=ids,
            media=media,
        )

    def plan_execution(
        self,
        storyboard: Storyboard,
        *,
        scene_id: int | None = None,
        scene_ids: Sequence[int] | None = None,
        scene_range: tuple[int, int] | None = None,
        media: Literal["images", "videos", "both"] = "both",
        retry_failed: bool = False,
    ) -> PartialExecutionPlan:
        """Resolve which scenes/media would run (no GPU)."""
        ids = resolve_scene_ids(
            storyboard,
            scene_id=scene_id,
            scene_ids=scene_ids,
            scene_range=scene_range,
            retry_failed=retry_failed,
        )
        estimate = estimate_generation_cost(
            storyboard, scene_ids=ids, media=media
        )
        return PartialExecutionPlan(
            scene_ids=ids,
            media=media,
            retry_failed=retry_failed,
            estimate=estimate,
        )

    def execute(
        self,
        storyboard: Storyboard,
        *,
        scene_id: int | None = None,
        scene_ids: Sequence[int] | None = None,
        scene_range: tuple[int, int] | None = None,
        media: Literal["images", "videos", "both"] = "both",
        retry_failed: bool = False,
        image_generator: ImageGeneratorFn | None = None,
        video_generator: VideoGeneratorFn | None = None,
        project_memory: ProjectMemory | None = None,
        dry_run: bool | None = None,
        persist: bool = True,
    ) -> PartialExecutionResult:
        """Partially generate images and/or videos for selected scenes.

        When generators are omitted, runs as a dry-run (plan + estimate only).
        Public :meth:`DirectorPipeline.generate` is unchanged.
        """
        plan = self.plan_execution(
            storyboard,
            scene_id=scene_id,
            scene_ids=scene_ids,
            scene_range=scene_range,
            media=media,
            retry_failed=retry_failed,
        )
        is_dry = dry_run if dry_run is not None else (
            image_generator is None and video_generator is None
        )
        if is_dry:
            return PartialExecutionResult(
                plan=plan,
                storyboard=storyboard,
                dry_run=True,
            )

        board = storyboard
        generated_images: list[int] = []
        generated_videos: list[int] = []
        skipped: list[int] = []
        errors: dict[str, str] = {}

        for sid in plan.scene_ids:
            scene = board.scene_by_id(sid)
            if scene.is_locked:
                skipped.append(sid)
                continue

            if plan.media in {"images", "both"} and image_generator is not None:
                if scene.status in {
                    SceneLifecycle.APPROVED,
                    SceneLifecycle.IMAGE_GENERATED,
                } or (scene.is_failed and scene.status == SceneLifecycle.IMAGE_GENERATED):
                    try:
                        prompt = scene.image_prompt or scene.description
                        image = image_generator(prompt)
                        asset_id = None
                        if project_memory is not None and project_memory.registry:
                            record = project_memory.registry.register(
                                kind=AssetKind.IMAGE,
                                slug=f"scene_{sid}_image",
                                label=scene.title,
                                refs={"url": image.url} if image.url else {},
                                metadata={"scene_id": sid, "source": "studio"},
                            )
                            asset_id = record.id
                        board = self._commit_scene(
                            board,
                            sid,
                            status=SceneLifecycle.IMAGE_GENERATED,
                            change_summary="image generated",
                            extra_updates={
                                "image": image,
                                "image_asset_id": asset_id,
                            },
                            clear_error=True,
                            persist=False,
                            force_status=True,
                        )
                        generated_images.append(sid)
                    except Exception as exc:  # noqa: BLE001
                        errors[str(sid)] = str(exc)
                        board = self._commit_scene(
                            board,
                            sid,
                            status=scene.status,
                            change_summary="image generation failed",
                            extra_updates={"error": str(exc)},
                            clear_error=False,
                            persist=False,
                            force_status=True,
                        )

            scene = board.scene_by_id(sid)
            if plan.media in {"videos", "both"} and video_generator is not None:
                if scene.status in {
                    SceneLifecycle.IMAGE_APPROVED,
                    SceneLifecycle.VIDEO_GENERATED,
                }:
                    try:
                        prompt = scene.image_prompt or scene.description
                        source = scene.image.url if scene.image else None
                        video = video_generator(
                            prompt,
                            source_image=source,
                            duration=scene.duration_seconds,
                        )
                        asset_id = None
                        if project_memory is not None:
                            record = register_scene_video(
                                project_memory,
                                scene_id=sid,
                                title=scene.title,
                                url=video.url,
                                source_image_urls=[source] if source else None,
                            )
                            asset_id = record.id
                            video = video.model_copy(update={"asset_id": asset_id})
                        board = self._commit_scene(
                            board,
                            sid,
                            status=SceneLifecycle.VIDEO_GENERATED,
                            change_summary="video generated",
                            extra_updates={
                                "video": video,
                                "video_asset_id": asset_id,
                            },
                            clear_error=True,
                            persist=False,
                            force_status=True,
                        )
                        generated_videos.append(sid)
                    except Exception as exc:  # noqa: BLE001
                        errors[str(sid)] = str(exc)
                        board = self._commit_scene(
                            board,
                            sid,
                            status=scene.status,
                            change_summary="video generation failed",
                            extra_updates={"error": str(exc)},
                            clear_error=False,
                            persist=False,
                            force_status=True,
                        )

        if persist:
            board = self.save(board)
        return PartialExecutionResult(
            plan=plan,
            storyboard=board,
            dry_run=False,
            generated_images=generated_images,
            generated_videos=generated_videos,
            skipped=skipped,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _commit_scene(
        self,
        storyboard: Storyboard,
        scene_id: int,
        *,
        status: SceneLifecycle,
        change_summary: str,
        extra_updates: dict[str, Any] | None = None,
        clear_error: bool = True,
        persist: bool = True,
        force_status: bool = False,
    ) -> Storyboard:
        scene = storyboard.scene_by_id(scene_id)
        if not force_status:
            assert_transition(scene.status, status)

        # Snapshot current state before mutation (version history).
        snap = scene.snapshot(change_summary=change_summary)
        versions = list(scene.versions) + [snap]
        updates: dict[str, Any] = {
            "status": status,
            "version": scene.version + 1,
            "versions": versions,
            "updated_at": _utc_iso(),
        }
        if clear_error:
            updates["error"] = None
        if extra_updates:
            updates.update(extra_updates)

        new_scene = scene.model_copy(update=updates)
        scenes = [
            new_scene if item.id == scene_id else item for item in storyboard.scenes
        ]
        board = storyboard.model_copy(
            update={
                "scenes": scenes,
                "version": storyboard.version + 1,
                "updated_at": _utc_iso(),
            }
        )
        if persist:
            board = self.save(board)
        return board
