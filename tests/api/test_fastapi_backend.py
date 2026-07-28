"""Integration tests for Sprint 6.0 FastAPI backend."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import get_copilot_service, get_project_service, reset_api_singletons
from src.api.services.projects import ProjectService
from src.copilot.service import CopilotService
from src.memory.store import ProjectMemoryStore
from src.models.image import ImageResult
from src.models.memory import ProjectMemory
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.models.storyboard import Scene, Storyboard
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore


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
                    url=f"https://x/{s.id}.png",
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
    app = create_app(enable_cors=False)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_copilot_service] = lambda: copilot

    class _FakePipeline:
        def generate(self, topic: str, progress_callback=None) -> PipelineResult:
            if progress_callback is not None:
                from src.progress import ProgressUpdate

                progress_callback(
                    ProgressUpdate(
                        message="fake progress",
                        fraction=0.5,
                        stage_panel="",
                        stages={"Director": 0.5},
                    )
                )
            return _fake_pipeline_result(topic)

    monkeypatch.setattr(
        "src.api.routes.projects.build_pipeline",
        lambda: _FakePipeline(),
    )
    monkeypatch.setattr(
        "src.api.services.projects.image_generator_fn",
        lambda prompt: ImageResult(prompt=prompt, url="https://cdn.example/img.png"),
    )
    monkeypatch.setattr(
        "src.api.routes.images.image_generator_fn",
        lambda prompt: ImageResult(prompt=prompt, url="https://cdn.example/img.png"),
    )

    with TestClient(app) as client:
        yield client, service

    app.dependency_overrides.clear()
    reset_api_singletons()


def test_health_and_openapi(api_client) -> None:
    client, _ = api_client
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "arahus-api"

    docs = client.get("/openapi.json")
    assert docs.status_code == 200
    paths = docs.json()["paths"]
    assert "/projects" in paths
    assert "/projects/{project_id}/generate" in paths
    assert "/projects/{project_id}/storyboard" in paths
    assert "/projects/{project_id}/storyboard/order" in paths
    assert "/scene/{scene_id}/image" in paths
    assert "/scene/{scene_id}/video" in paths
    assert "/assets" in paths
    assert "/chat" in paths
    # WebSocket routes are registered on the app (may be omitted from paths map).
    assert any(
        getattr(route, "path", "") == "/ws/projects/{project_id}"
        for route in client.app.routes
    )


def test_create_get_list_project(api_client) -> None:
    client, _ = api_client
    created = client.post("/projects", json={"topic": "Napoleon at Waterloo"})
    assert created.status_code == 201
    body = created.json()
    assert body["topic"] == "Napoleon at Waterloo"
    assert body["id"]
    project_id = body["id"]

    fetched = client.get(f"/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project_id

    listed = client.get("/projects")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1


def test_generate_sync_and_storyboard(api_client) -> None:
    client, service = api_client
    project_id = client.post(
        "/projects", json={"topic": "Fall of Constantinople"}
    ).json()["id"]

    gen = client.post(f"/projects/{project_id}/generate?wait=true", json={})
    assert gen.status_code == 200
    payload = gen.json()
    assert payload["status"] == "ready"
    assert payload["scene_count"] == 4
    assert payload["review_score"] == 90

    board = client.get(f"/projects/{project_id}/storyboard")
    assert board.status_code == 200
    assert len(board.json()["scenes"]) == 4
    assert service.load(project_id).status == "ready"


def test_patch_scene_and_image_dry_run(api_client) -> None:
    client, _ = api_client
    project_id = client.post("/projects", json={"topic": "Mars Colony"}).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})

    patched = client.patch(
        "/storyboard/2",
        params={"project_id": project_id},
        json={"emotion": "awe", "camera": "slow push-in"},
    )
    assert patched.status_code == 200
    assert patched.json()["emotion"] == "awe"
    assert patched.json()["camera"] == "slow push-in"

    image = client.post(
        "/scene/2/image",
        json={"project_id": project_id, "dry_run": True},
    )
    assert image.status_code == 200
    assert image.json()["dry_run"] is True
    assert image.json()["estimate"] is not None


def test_reorder_storyboard_scenes(api_client) -> None:
    client, _ = api_client
    project_id = client.post(
        "/projects", json={"topic": "Hannibal Alps"}
    ).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    before = client.get(f"/projects/{project_id}/storyboard").json()
    ids = [scene["id"] for scene in before["scenes"]]
    reordered = list(reversed(ids))

    result = client.put(
        f"/projects/{project_id}/storyboard/order",
        json={"scene_ids": reordered},
    )
    assert result.status_code == 200
    assert [scene["id"] for scene in result.json()["scenes"]] == reordered

    bad = client.put(
        f"/projects/{project_id}/storyboard/order",
        json={"scene_ids": [1, 2]},
    )
    assert bad.status_code == 400


def test_image_generate_and_assets(api_client) -> None:
    client, service = api_client
    project_id = client.post("/projects", json={"topic": "Bitcoin ETF"}).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    service.memory_store.save(
        ProjectMemory(project_id=project_id, topic="Bitcoin ETF")
    )

    image = client.post(
        "/scene/1/image",
        json={"project_id": project_id, "dry_run": False},
    )
    assert image.status_code == 200
    body = image.json()
    assert body["url"] == "https://cdn.example/img.png"
    assert body["asset_id"] is not None

    assets = client.get("/assets", params={"project_id": project_id})
    assert assets.status_code == 200
    assert assets.json()["count"] >= 1


def test_chat_and_export(api_client) -> None:
    client, _ = api_client
    project_id = client.post("/projects", json={"topic": "Chat Topic"}).json()["id"]
    chat = client.post("/chat", json={"message": "help", "project_id": project_id})
    assert chat.status_code == 200
    assert chat.json()["reply"]
    assert "commands" in chat.json()

    export = client.get(f"/projects/{project_id}/export")
    assert export.status_code == 200
    assert export.json()["project_id"] == project_id


def test_build_pipeline_import_still_works() -> None:
    from src.api import build_pipeline, create_app, generate_pipeline_result

    assert callable(build_pipeline)
    assert callable(generate_pipeline_result)
    assert callable(create_app)


def test_director_pipeline_generate_signature_unchanged() -> None:
    import inspect

    from src.pipeline import DirectorPipeline

    params = list(inspect.signature(DirectorPipeline.generate).parameters)
    assert params[1] == "topic"
