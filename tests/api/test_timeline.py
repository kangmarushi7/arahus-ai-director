"""Sprint 6.4 — Timeline editor integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import (
    get_copilot_service,
    get_project_service,
    get_timeline_service,
    reset_api_singletons,
)
from src.api.services.projects import ProjectService
from src.copilot.service import CopilotService
from src.memory.store import ProjectMemoryStore
from src.models.image import ImageResult
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.models.storyboard import Scene, Storyboard
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore
from src.timeline.service import TimelineService
from src.timeline.store import TimelineStore


def _four_plans(topic: str) -> StoryPlan:
    titles = ("One", "Two", "Three", "Four")
    return StoryPlan(
        topic=topic,
        scenes=[
            ScenePlan(
                id=i,
                title=title,
                description=f"{title} description with enough words here " * 6,
                subject=f"subject {title}",
                environment="location",
                action=f"action {title}",
                camera_shot="wide",
                camera_movement="static",
                camera_angle="eye-level",
                lens="35mm",
                lighting="soft",
                emotion="calm",
                composition="balanced",
            )
            for i, title in enumerate(titles, start=1)
        ],
    )


def _fake_pipeline_result(topic: str) -> PipelineResult:
    story = _four_plans(topic)
    plan = story.to_director_plan()
    board = Storyboard(
        topic=topic,
        scenes=[
            Scene(
                id=s.id,
                title=s.title,
                description=s.description,
                image_prompt=f"prompt {s.id}",
                image=ImageResult(
                    prompt=f"prompt {s.id}",
                    url=f"https://cdn.example/{s.id}.png",
                ),
            )
            for s in plan.scenes
        ],
    )
    return PipelineResult(
        topic=topic,
        research=ResearchResult(topic=topic, key_people=["Hero"]),
        plan=plan,
        storyboard=board,
        review=ReviewResult(
            overall_score=90,
            domain_accuracy=90,
            visual_quality=90,
            scene_continuity=90,
            prompt_quality=90,
            approved=True,
            issues=[],
            recommendations=[],
        ),
        images=[
            GeneratedImageInfo(
                scene_id=s.id,
                title=s.title,
                prompt=s.image_prompt or "",
                url=s.image.url if s.image else None,
            )
            for s in board.scenes
        ],
        project_id="",
        run_id="test-run",
    )


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_api_singletons()
    service = ProjectService(
        root=tmp_path,
        studio=StoryboardStudio(store=StoryboardStore(root=tmp_path)),
        memory_store=ProjectMemoryStore(root=tmp_path),
    )
    copilot = CopilotService(
        root=tmp_path,
        studio=service.studio,
        memory_store=service.memory_store,
    )
    timelines = TimelineService(store=TimelineStore(root=tmp_path))
    app = create_app(enable_cors=False)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_copilot_service] = lambda: copilot
    app.dependency_overrides[get_timeline_service] = lambda: timelines

    class _FakePipeline:
        def generate(self, topic: str, progress_callback=None) -> PipelineResult:
            return _fake_pipeline_result(topic)

    monkeypatch.setattr(
        "src.api.routes.projects.build_pipeline",
        lambda: _FakePipeline(),
    )

    with TestClient(app) as client:
        yield client, service, timelines

    app.dependency_overrides.clear()
    reset_api_singletons()


def _seed(client: TestClient) -> str:
    project_id = client.post("/projects", json={"topic": "Timeline Alps"}).json()[
        "id"
    ]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    return project_id


def test_timeline_sync_tracks_and_persist(api_client) -> None:
    client, service, timelines = api_client
    project_id = _seed(client)

    synced = client.post(
        f"/projects/{project_id}/timeline/sync",
        json={"preserve_non_video": True},
    )
    assert synced.status_code == 200
    body = synced.json()
    kinds = [t["kind"] for t in body["tracks"]]
    assert kinds == ["video", "voice", "music", "sfx", "subtitles"]
    video = next(t for t in body["tracks"] if t["kind"] == "video")
    assert len(video["clips"]) == 4
    assert body["duration_seconds"] > 0
    assert (service.root / project_id / "timeline.json").is_file()

    loaded = client.get(f"/projects/{project_id}/timeline")
    assert loaded.status_code == 200
    assert loaded.json()["version"] == body["version"]
    assert timelines.load(project_id) is not None


def test_timeline_reorder_resize_split_merge_delete_duplicate(api_client) -> None:
    client, _, _ = api_client
    project_id = _seed(client)
    timeline = client.post(
        f"/projects/{project_id}/timeline/sync", json={}
    ).json()
    video = next(t for t in timeline["tracks"] if t["kind"] == "video")
    track_id = video["id"]
    clip_ids = [c["id"] for c in video["clips"]]

    reordered = list(reversed(clip_ids))
    order = client.put(
        f"/projects/{project_id}/timeline/order",
        json={"track_id": track_id, "clip_ids": reordered},
    )
    assert order.status_code == 200
    video = next(
        t for t in order.json()["tracks"] if t["kind"] == "video"
    )
    assert [c["id"] for c in video["clips"]] == reordered
    assert video["clips"][0]["start_seconds"] == 0

    first = video["clips"][0]
    resized = client.post(
        f"/projects/{project_id}/timeline/clips/{first['id']}/resize",
        json={"duration_seconds": 3.5},
    )
    assert resized.status_code == 200
    first = next(
        c
        for t in resized.json()["tracks"]
        if t["kind"] == "video"
        for c in t["clips"]
        if c["id"] == first["id"]
    )
    assert first["duration_seconds"] == 3.5

    split_at = first["start_seconds"] + 1.0
    split = client.post(
        f"/projects/{project_id}/timeline/clips/{first['id']}/split",
        json={"at_seconds": split_at},
    )
    assert split.status_code == 200
    video = next(t for t in split.json()["tracks"] if t["kind"] == "video")
    assert len(video["clips"]) == 5

    a, b = video["clips"][0], video["clips"][1]
    merged = client.post(
        f"/projects/{project_id}/timeline/merge",
        json={"clip_ids": [a["id"], b["id"]]},
    )
    assert merged.status_code == 200
    video = next(t for t in merged.json()["tracks"] if t["kind"] == "video")
    assert len(video["clips"]) == 4

    clip = video["clips"][0]
    dup = client.post(
        f"/projects/{project_id}/timeline/clips/{clip['id']}/duplicate"
    )
    assert dup.status_code == 200
    video = next(t for t in dup.json()["tracks"] if t["kind"] == "video")
    assert len(video["clips"]) == 5

    victim = video["clips"][-1]["id"]
    deleted = client.delete(
        f"/projects/{project_id}/timeline/clips/{victim}?close_gaps=true"
    )
    assert deleted.status_code == 200
    video = next(t for t in deleted.json()["tracks"] if t["kind"] == "video")
    assert len(video["clips"]) == 4


def test_timeline_transitions_preview_export_queue(api_client) -> None:
    client, _, _ = api_client
    project_id = _seed(client)
    timeline = client.post(
        f"/projects/{project_id}/timeline/sync", json={}
    ).json()
    clip = next(t for t in timeline["tracks"] if t["kind"] == "video")["clips"][0]

    trans = client.post(
        f"/projects/{project_id}/timeline/clips/{clip['id']}/transition",
        json={
            "transition_in": "fade",
            "transition_out": "dissolve",
            "transition_duration": 0.5,
        },
    )
    assert trans.status_code == 200
    updated = next(
        c
        for t in trans.json()["tracks"]
        if t["kind"] == "video"
        for c in t["clips"]
        if c["id"] == clip["id"]
    )
    assert updated["transition_in"] == "fade"
    assert updated["transition_out"] == "dissolve"

    seek = client.post(
        f"/projects/{project_id}/timeline/seek",
        json={"seconds": 2.0},
    )
    assert seek.status_code == 200
    assert seek.json()["playhead_seconds"] == 2.0
    assert "preview" in seek.json()

    preview = client.get(
        f"/projects/{project_id}/timeline/preview",
        params={"seconds": 1.0},
    )
    assert preview.status_code == 200
    assert preview.json()["playhead_seconds"] == 1.0

    for aspect in ("16:9", "9:16", "1:1"):
        queued = client.post(
            f"/projects/{project_id}/timeline/export",
            json={"format": "mp4", "aspect": aspect},
        )
        assert queued.status_code == 200
    queue = queued.json()["export_queue"]
    assert len(queue) == 3
    assert all(j["format"] == "mp4" for j in queue)
    assert {j["aspect"] for j in queue} == {"16:9", "9:16", "1:1"}

    export = client.get(f"/projects/{project_id}/export")
    assert export.status_code == 200
    assert export.json()["timeline"] is not None


def test_timeline_openapi_paths(api_client) -> None:
    client, _, _ = api_client
    paths = client.get("/openapi.json").json()["paths"]
    assert "/projects/{project_id}/timeline" in paths
    assert "/projects/{project_id}/timeline/sync" in paths
    assert "/projects/{project_id}/timeline/export" in paths


def test_pipeline_unchanged() -> None:
    import inspect

    from src.pipeline import DirectorPipeline

    assert list(inspect.signature(DirectorPipeline.generate).parameters)[1] == "topic"
