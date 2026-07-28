"""Unit tests for Sprint 5.4 Storyboard Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Type, TypeVar

import pytest
from pydantic import BaseModel

from src.agents.review import ReviewAgent
from src.domain.models import DomainInfo, DomainType
from src.models.image import ImageResult, VideoResult
from src.models.memory import ProjectMemory
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.studio import (
    SceneLifecycle,
    StoryboardStore,
    StoryboardStudio,
    TransitionError,
    assert_transition,
    can_transition,
    estimate_generation_cost,
    resolve_scene_ids,
)

T = TypeVar("T", bound=BaseModel)


def _four_plans(topic: str = "Napoleon at Waterloo") -> StoryPlan:
    titles = ("Dawn", "Advance", "Clash", "Aftermath")
    return StoryPlan(
        topic=topic,
        scenes=[
            ScenePlan(
                id=i,
                title=title,
                description=f"{title} beat with enough cinematic narrative words " * 5,
                subject=f"subject {title}",
                environment="Waterloo field",
                action=f"action {title}",
                camera_shot="close up" if i == 3 else "wide",
                camera_movement="static",
                camera_angle="eye-level",
                lens="35mm",
                lighting="overcast",
                emotion="tension" if i == 3 else "resolve",
                composition="balanced",
                continuity=f"from beat {i - 1}",
                negative_prompt="blurry",
            )
            for i, title in enumerate(titles, start=1)
        ],
    )


class _FakeReviewLLM:
    def __init__(self, result: ReviewResult) -> None:
        self._result = result
        self.progress_callback = None

    def generate_json(self, prompt: str, response_model: Type[T]) -> T:
        assert response_model is ReviewResult
        return self._result  # type: ignore[return-value]


def _review(score: float, *, approved: bool | None = None) -> ReviewResult:
    flag = approved if approved is not None else score >= 85
    return ReviewResult(
        overall_score=score,
        domain_accuracy=score,
        visual_quality=score,
        scene_continuity=score,
        prompt_quality=score,
        approved=flag,
        issues=[],
        recommendations=[],
    )


class TestLifecycleTransitions:
    def test_happy_path_transitions(self) -> None:
        order = [
            SceneLifecycle.DRAFT,
            SceneLifecycle.APPROVED,
            SceneLifecycle.IMAGE_GENERATED,
            SceneLifecycle.IMAGE_APPROVED,
            SceneLifecycle.VIDEO_GENERATED,
            SceneLifecycle.VIDEO_APPROVED,
            SceneLifecycle.LOCKED,
        ]
        for current, target in zip(order, order[1:], strict=False):
            assert can_transition(current, target)
            assert_transition(current, target)

    def test_illegal_skip_raises(self) -> None:
        with pytest.raises(TransitionError):
            assert_transition(SceneLifecycle.DRAFT, SceneLifecycle.IMAGE_GENERATED)

    def test_locked_is_terminal(self) -> None:
        with pytest.raises(TransitionError):
            assert_transition(SceneLifecycle.LOCKED, SceneLifecycle.DRAFT)


class TestPersistenceAndVersioning:
    def test_create_save_load_round_trip(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=True)
        assert board.status == SceneLifecycle.DRAFT
        assert len(board.scenes) == 4
        assert board.scenes[0].versions  # initial snapshot

        loaded = studio.load(board.project_id)
        assert loaded is not None
        assert loaded.topic == board.topic
        assert loaded.scenes[2].title == "Clash"
        assert loaded.scenes[2].emotion == "tension"

    def test_approve_bumps_version_history(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        before = board.scenes[0].version
        board = studio.approve_scene(board, 1, persist=False)
        scene = board.scene_by_id(1)
        assert scene.status == SceneLifecycle.APPROVED
        assert scene.version == before + 1
        assert len(scene.versions) >= 2
        assert scene.versions[-1].status == SceneLifecycle.DRAFT

    def test_regenerate_image_rolls_back(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        board = studio.approve_scene(board, 1, persist=False)
        board = studio.transition_scene(
            board, 1, SceneLifecycle.IMAGE_GENERATED, persist=False
        )
        board = studio._commit_scene(
            board,
            1,
            status=SceneLifecycle.IMAGE_GENERATED,
            change_summary="attach",
            extra_updates={
                "image": ImageResult(prompt="x", url="https://x/a.png"),
            },
            persist=False,
            force_status=True,
        )
        board = studio.regenerate(board, 1, "image", persist=False)
        scene = board.scene_by_id(1)
        assert scene.status == SceneLifecycle.APPROVED
        assert scene.image is None
        assert any("regenerate image" in v.change_summary for v in scene.versions)


class TestReviewIntegration:
    def test_review_auto_approves_drafts_when_score_high(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(
            store=StoryboardStore(root=tmp_path),
            approval_threshold=85.0,
        )
        board = studio.create_from_plan(_four_plans(), persist=False)
        agent = ReviewAgent(_FakeReviewLLM(_review(92)))  # type: ignore[arg-type]
        board, result = studio.review(
            board,
            agent,
            domain_info=DomainInfo(
                domain=DomainType.HISTORY,
                confidence=0.9,
                reasoning="history",
                keywords=["napoleon"],
            ),
            persist=False,
        )
        assert result.approved is True
        assert all(s.status == SceneLifecycle.APPROVED for s in board.scenes)

    def test_review_does_not_approve_when_score_low(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(
            store=StoryboardStore(root=tmp_path),
            approval_threshold=85.0,
        )
        board = studio.create_from_plan(_four_plans(), persist=False)
        agent = ReviewAgent(_FakeReviewLLM(_review(62, approved=True)))  # type: ignore[arg-type]
        board, result = studio.review(board, agent, persist=False)
        assert result.approved is False
        assert all(s.status == SceneLifecycle.DRAFT for s in board.scenes)


class TestCostEstimation:
    def test_estimate_images_and_videos(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        for sid in (1, 2, 3, 4):
            board = studio.approve_scene(board, sid, persist=False)

        estimate = estimate_generation_cost(
            board,
            media="both",
            cost_per_image=0.02,
            cost_per_video_second=0.05,
        )
        # Videos need IMAGE_APPROVED — none yet, so only images counted.
        assert estimate.image_count == 4
        assert estimate.video_count == 0
        assert estimate.estimated_cost_usd == pytest.approx(0.08)
        assert estimate.estimated_gpu_seconds > 0

        # Promote two scenes to image-approved → video estimate appears.
        for sid in (1, 2):
            board = studio.transition_scene(
                board, sid, SceneLifecycle.IMAGE_GENERATED, persist=False
            )
            board = studio.approve_image(board, sid, persist=False)

        estimate = studio.estimate(board, media="videos")
        assert estimate.video_count == 2
        assert estimate.video_duration_seconds == pytest.approx(10.0)
        assert estimate.estimated_cost_usd == pytest.approx(0.5)


class TestPartialExecution:
    def test_resolve_single_range_and_failed(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        assert resolve_scene_ids(board, scene_id=2) == [2]
        assert resolve_scene_ids(board, scene_range=(2, 4)) == [2, 3, 4]

        board = studio._commit_scene(
            board,
            3,
            status=SceneLifecycle.APPROVED,
            change_summary="fail",
            extra_updates={"error": "boom"},
            clear_error=False,
            persist=False,
            force_status=True,
        )
        assert resolve_scene_ids(board, retry_failed=True) == [3]

    def test_dry_run_execute(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        for sid in (1, 2, 3, 4):
            board = studio.approve_scene(board, sid, persist=False)
        result = studio.execute(board, media="images", dry_run=True)
        assert result.dry_run is True
        assert result.plan.estimate is not None
        assert result.plan.estimate.image_count == 4

    def test_execute_images_only_single_scene(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        board = studio.approve_scene(board, 2, persist=False)
        memory = ProjectMemory(project_id=board.project_id, topic=board.topic)

        def _img(prompt: str) -> ImageResult:
            return ImageResult(prompt=prompt, url="https://cdn.example/s2.png")

        result = studio.execute(
            board,
            scene_id=2,
            media="images",
            image_generator=_img,
            project_memory=memory,
            persist=False,
        )
        assert result.dry_run is False
        assert result.generated_images == [2]
        scene = result.storyboard.scene_by_id(2)
        assert scene.status == SceneLifecycle.IMAGE_GENERATED
        assert scene.image is not None
        assert scene.image_asset_id is not None
        assert memory.registry is not None
        assert memory.registry.get_by_slug("scene_2_image") is not None

    def test_execute_videos_only_after_image_approved(self, tmp_path: Path) -> None:
        studio = StoryboardStudio(store=StoryboardStore(root=tmp_path))
        board = studio.create_from_plan(_four_plans(), persist=False)
        board = studio.approve_scene(board, 1, persist=False)
        board = studio.transition_scene(
            board, 1, SceneLifecycle.IMAGE_GENERATED, persist=False
        )
        board = studio._commit_scene(
            board,
            1,
            status=SceneLifecycle.IMAGE_GENERATED,
            change_summary="img",
            extra_updates={
                "image": ImageResult(prompt="p", url="https://cdn.example/s1.png")
            },
            persist=False,
            force_status=True,
        )
        board = studio.approve_image(board, 1, persist=False)
        memory = ProjectMemory(project_id=board.project_id, topic=board.topic)

        def _vid(prompt: str, **kwargs: object) -> VideoResult:
            return VideoResult(
                prompt=prompt,
                url="https://cdn.example/s1.mp4",
                duration_seconds=float(kwargs.get("duration") or 5),
                source_image=str(kwargs.get("source_image") or ""),
            )

        result = studio.execute(
            board,
            scene_id=1,
            media="videos",
            video_generator=_vid,
            project_memory=memory,
            persist=False,
        )
        assert result.generated_videos == [1]
        scene = result.storyboard.scene_by_id(1)
        assert scene.status == SceneLifecycle.VIDEO_GENERATED
        assert scene.video_asset_id is not None


class TestPipelineApiUntouched:
    def test_director_pipeline_generate_signature(self) -> None:
        import inspect

        from src.pipeline import DirectorPipeline

        sig = inspect.signature(DirectorPipeline.generate)
        params = list(sig.parameters)
        assert params[0] == "self"
        assert params[1] == "topic"
        assert "progress_callback" in params
