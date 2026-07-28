"""Sprint 6.6 — Export & Publishing integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import (
    get_audio_studio,
    get_copilot_service,
    get_export_studio,
    get_project_service,
    get_timeline_service,
    reset_api_singletons,
)
from src.api.services.projects import ProjectService
from src.audio.service import AudioStudioService
from src.audio.store import AudioProjectStore
from src.copilot.service import CopilotService
from src.export.providers import build_publish_provider
from src.export.service import ExportStudioService
from src.export.store import ExportStore
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
                image=ImageResult(prompt=f"prompt {s.id}", url=f"https://x/{s.id}.png"),
            )
            for s in plan.scenes
        ],
    )
    return PipelineResult(
        topic=topic,
        research=ResearchResult(topic=topic, key_people=["Napoleon"]),
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
    timelines = TimelineService(store=TimelineStore(root=tmp_path))
    audio = AudioStudioService(
        root=tmp_path,
        store=AudioProjectStore(root=tmp_path),
        timeline_service=timelines,
    )

    def _project(project_id: str) -> dict:
        try:
            return service.to_response(service.require(project_id))
        except KeyError:
            return {"id": project_id}

    def _storyboard(project_id: str) -> dict | None:
        board = service.studio.load(project_id)
        return board.to_dict() if board else None

    def _memory(project_id: str) -> dict | None:
        memory = service.memory_store.load(project_id)
        return memory.to_dict() if memory else None

    export = ExportStudioService(
        root=tmp_path,
        store=ExportStore(root=tmp_path),
        timeline_service=timelines,
        audio_service=audio,
        project_loader=_project,
        storyboard_loader=_storyboard,
        memory_loader=_memory,
    )
    copilot = CopilotService(
        root=tmp_path,
        studio=service.studio,
        memory_store=service.memory_store,
    )
    app = create_app(enable_cors=False)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_timeline_service] = lambda: timelines
    app.dependency_overrides[get_audio_studio] = lambda: audio
    app.dependency_overrides[get_export_studio] = lambda: export
    app.dependency_overrides[get_copilot_service] = lambda: copilot

    class _FakePipeline:
        def generate(self, topic: str, progress_callback=None) -> PipelineResult:
            return _fake_pipeline_result(topic)

    monkeypatch.setattr(
        "src.api.routes.projects.build_pipeline",
        lambda: _FakePipeline(),
    )

    with TestClient(app) as client:
        yield client, service, export

    app.dependency_overrides.clear()
    reset_api_singletons()


def _seed(client: TestClient) -> str:
    project_id = client.post("/projects", json={"topic": "Export Alps"}).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    return project_id


def test_publish_providers_are_stubs() -> None:
    for platform in ("youtube", "instagram", "tiktok", "x"):
        provider = build_publish_provider(platform)
        health = provider.healthcheck()
        assert health["live"] is False
        assert health["oauth"] is False
        assert health["platform"] == ("x" if platform == "x" else platform)


def test_export_pipeline_and_publish(api_client) -> None:
    client, _, export = api_client
    project_id = _seed(client)

    presets = client.get("/export/presets").json()["presets"]
    assert {p["id"] for p in presets} >= {
        "youtube_shorts",
        "instagram_reels",
        "tiktok",
        "youtube",
        "x",
        "custom",
    }

    providers = client.get("/export/providers").json()["providers"]
    assert len(providers) == 4
    assert all(p["oauth"] is False for p in providers)

    # Keep legacy JSON export
    legacy = client.get(f"/projects/{project_id}/export").json()
    assert legacy["project_id"] == project_id
    assert legacy["storyboard"] is not None

    state = client.post(
        f"/projects/{project_id}/exports",
        json={"preset": "youtube_shorts", "format": "mp4", "process": True},
    ).json()
    assert len(state["queue"]) == 1
    job = state["queue"][0]
    assert job["status"] == "ready"
    assert job["progress"] == 1.0
    assert job["output_path"]
    assert job["package_path"]
    assert Path(job["package_path"]).is_dir()
    assert (Path(job["package_path"]) / "storyboard.json").is_file()
    assert (Path(job["package_path"]) / "prompts.json").is_file()
    assert (Path(job["package_path"]) / "media_assets.json").is_file()
    assert (Path(job["package_path"]) / "metadata.json").is_file()
    assert len(state["history"]) == 1
    assert state["history"][0]["version"] == 1

    # Image sequence + custom
    state = client.post(
        f"/projects/{project_id}/exports",
        json={
            "preset": "custom",
            "format": "image_sequence",
            "width": 640,
            "height": 360,
            "fps": 12,
            "process": True,
        },
    ).json()
    seq_job = state["queue"][-1]
    assert seq_job["status"] == "ready"
    assert Path(seq_job["output_path"]).is_dir()

    # Publish now (stub)
    state = client.post(
        f"/projects/{project_id}/publish",
        json={
            "render_job_id": job["id"],
            "platform": "youtube",
            "title": "Alps cut",
            "run": True,
        },
    ).json()
    pub = state["publishes"][-1]
    assert pub["status"] == "published"
    assert pub["external_url"]
    assert pub["provider"] == "youtube"

    # Schedule later
    state = client.post(
        f"/projects/{project_id}/publish",
        json={
            "render_job_id": job["id"],
            "platform": "tiktok",
            "title": "Later",
            "schedule_at": "2099-01-01T12:00:00+00:00",
            "run": True,
        },
    ).json()
    scheduled = state["publishes"][-1]
    assert scheduled["status"] == "scheduled"
    assert scheduled["schedule_at"]

    history = client.get(f"/projects/{project_id}/exports/history").json()
    assert len(history["history"]) >= 2
    hist_for_job = next(
        h for h in history["history"] if h["render_job_id"] == job["id"]
    )
    assert hist_for_job["publish_status"] in ("published", "scheduled")
    assert hist_for_job["settings"]["preset"] == "youtube_shorts"

    # Pause / resume path without auto-process
    state = client.post(
        f"/projects/{project_id}/exports",
        json={"preset": "x", "format": "gif", "process": False},
    ).json()
    pending = state["queue"][-1]
    assert pending["status"] == "queued"
    state = client.post(
        f"/projects/{project_id}/exports/{pending['id']}/pause"
    ).json()
    paused = next(j for j in state["queue"] if j["id"] == pending["id"])
    assert paused["status"] == "paused"
    state = client.post(
        f"/projects/{project_id}/exports/{pending['id']}/resume?process=true"
    ).json()
    resumed = next(j for j in state["queue"] if j["id"] == pending["id"])
    assert resumed["status"] == "ready"

    # Cancel a fresh queued job
    state = client.post(
        f"/projects/{project_id}/exports",
        json={"preset": "youtube", "format": "mov", "process": False},
    ).json()
    to_cancel = state["queue"][-1]
    state = client.post(
        f"/projects/{project_id}/exports/{to_cancel['id']}/cancel"
    ).json()
    cancelled = next(j for j in state["queue"] if j["id"] == to_cancel["id"])
    assert cancelled["status"] == "cancelled"

    # Retry cancelled
    state = client.post(
        f"/projects/{project_id}/exports/{to_cancel['id']}/retry?process=true"
    ).json()
    retried = next(j for j in state["queue"] if j["id"] == to_cancel["id"])
    assert retried["status"] == "ready"
    assert retried["attempt"] >= 1

    loaded = export.load(project_id)
    assert loaded is not None
    assert loaded.version >= 1
