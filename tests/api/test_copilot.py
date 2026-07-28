"""Sprint 6.3 — AI Copilot integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import get_copilot_service, get_project_service, reset_api_singletons
from src.api.services.projects import ProjectService
from src.copilot.parser import parse_intent
from src.copilot.service import CopilotService
from src.memory.store import ProjectMemoryStore
from src.models.image import ImageResult
from src.models.memory import AppearanceBible, CharacterBible, ProjectMemory
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.models.storyboard import Scene, Storyboard
from src.studio.models import Storyboard as StudioStoryboard
from src.studio.models import StoryboardScene
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
            return _fake_pipeline_result(topic)

    monkeypatch.setattr(
        "src.api.routes.projects.build_pipeline",
        lambda: _FakePipeline(),
    )
    monkeypatch.setattr(
        "src.api.services.projects.image_generator_fn",
        lambda prompt: ImageResult(prompt=prompt, url="https://cdn.example/img.png"),
    )

    with TestClient(app) as client:
        yield client, service, copilot

    app.dependency_overrides.clear()
    reset_api_singletons()


def _seed_project(client: TestClient, topic: str = "Copilot Alps") -> str:
    project_id = client.post("/projects", json={"topic": topic}).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    return project_id


def test_parser_core_intents() -> None:
    board = StudioStoryboard(
        project_id="p",
        topic="t",
        scenes=[
            StoryboardScene(id=1, title="A"),
            StoryboardScene(id=2, title="B"),
            StoryboardScene(id=3, title="C"),
            StoryboardScene(id=4, title="D"),
        ],
    )
    lighting = parse_intent("set scene 2 lighting to moonlight", storyboard=board)
    assert len(lighting) == 1
    assert lighting[0].type.value == "change_lighting"
    assert lighting[0].updates["lighting"] == "moonlight"

    camera = parse_intent("change camera on scene 1 to close-up dolly", storyboard=board)
    assert camera[0].type.value == "change_camera"

    regen = parse_intent("regenerate image for scene 3", storyboard=board)
    assert regen[0].type.value == "regenerate_image"
    assert regen[0].scene_id == 3

    duration = parse_intent("set duration of scene 2 to 8 seconds", storyboard=board)
    assert duration[0].type.value == "change_duration"
    assert duration[0].value == 8.0

    reorder = parse_intent("reverse the scenes", storyboard=board)
    assert reorder[0].scene_ids == [4, 3, 2, 1]

    style = parse_intent("change style to painterly cinematic", storyboard=board)
    assert style[0].type.value == "modify_style"


def test_copilot_propose_preview_execute_undo_redo(api_client) -> None:
    client, service, _ = api_client
    project_id = _seed_project(client)

    proposed = client.post(
        "/chat",
        json={
            "project_id": project_id,
            "message": "set scene 2 lighting to moonlight",
        },
    )
    assert proposed.status_code == 200
    body = proposed.json()
    assert body["proposal_id"]
    assert body["preview"]["command_count"] == 1
    assert body["commands"][0]["type"] == "change_lighting"
    # Not applied yet
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert board["scenes"][1]["lighting"] != "moonlight"

    executed = client.post(
        "/chat/execute",
        json={"project_id": project_id, "proposal_id": body["proposal_id"], "run_media": False},
    )
    assert executed.status_code == 200
    assert executed.json()["can_undo"] is True
    board = client.get(f"/projects/{project_id}/storyboard").json()
    scene2 = next(s for s in board["scenes"] if s["id"] == 2)
    assert scene2["lighting"] == "moonlight"

    undo = client.post("/chat/undo", json={"project_id": project_id})
    assert undo.status_code == 200
    board = client.get(f"/projects/{project_id}/storyboard").json()
    scene2 = next(s for s in board["scenes"] if s["id"] == 2)
    assert scene2["lighting"] != "moonlight"

    redo = client.post("/chat/redo", json={"project_id": project_id})
    assert redo.status_code == 200
    board = client.get(f"/projects/{project_id}/storyboard").json()
    scene2 = next(s for s in board["scenes"] if s["id"] == 2)
    assert scene2["lighting"] == "moonlight"

    history = client.get(f"/projects/{project_id}/chat")
    assert history.status_code == 200
    assert history.json()["can_undo"] is True
    assert len(history.json()["messages"]) >= 3
    assert (service.root / project_id / "chat.json").is_file()


def test_copilot_reorder_and_duration(api_client) -> None:
    client, _, _ = api_client
    project_id = _seed_project(client, topic="Reorder Copilot")

    proposed = client.post(
        "/chat",
        json={"project_id": project_id, "message": "reverse the scenes"},
    )
    assert proposed.status_code == 200
    client.post(
        "/chat/execute",
        json={"project_id": project_id, "run_media": False},
    )
    order = [
        s["id"]
        for s in client.get(f"/projects/{project_id}/storyboard").json()["scenes"]
    ]
    assert order == [4, 3, 2, 1]

    proposed = client.post(
        "/chat",
        json={
            "project_id": project_id,
            "message": "set duration of scene 4 to 9 seconds",
        },
    )
    client.post(
        "/chat/execute",
        json={"project_id": project_id, "run_media": False},
    )
    scene4 = next(
        s
        for s in client.get(f"/projects/{project_id}/storyboard").json()["scenes"]
        if s["id"] == 4
    )
    assert scene4["duration_seconds"] == 9.0


def test_copilot_regenerate_image_and_memory(api_client) -> None:
    client, service, _ = api_client
    project_id = _seed_project(client, topic="Regen Copilot")
    service.memory_store.save(
        ProjectMemory(
            project_id=project_id,
            topic="Regen Copilot",
            characters=[
                CharacterBible(
                    id="hero",
                    asset_id=1,
                    name="Napoleon Bonaparte",
                    appearance=AppearanceBible(age="30"),
                    notes="original",
                )
            ],
        )
    )

    proposed = client.post(
        "/chat",
        json={
            "project_id": project_id,
            "message": "regenerate image for scene 1",
        },
    )
    assert proposed.json()["commands"][0]["type"] == "regenerate_image"
    executed = client.post(
        "/chat/execute",
        json={"project_id": project_id, "run_media": True},
    )
    assert executed.status_code == 200
    scene1 = next(
        s
        for s in client.get(f"/projects/{project_id}/storyboard").json()["scenes"]
        if s["id"] == 1
    )
    assert scene1["image"] is not None
    assert scene1["image"]["url"]

    proposed = client.post(
        "/chat",
        json={
            "project_id": project_id,
            "message": "update character Napoleon to look older",
        },
    )
    assert proposed.status_code == 200
    assert proposed.json()["commands"][0]["type"] == "modify_character"
    client.post(
        "/chat/execute",
        json={"project_id": project_id, "run_media": False},
    )
    memory = service.memory_store.load(project_id)
    assert memory is not None
    assert memory.characters[0].appearance.age == "older"


def test_copilot_openapi_paths(api_client) -> None:
    client, _, _ = api_client
    paths = client.get("/openapi.json").json()["paths"]
    assert "/chat" in paths
    assert "/chat/execute" in paths
    assert "/chat/undo" in paths
    assert "/chat/redo" in paths
    assert "/projects/{project_id}/chat" in paths


def test_director_pipeline_unchanged_by_copilot() -> None:
    import inspect

    from src.pipeline import DirectorPipeline

    params = list(inspect.signature(DirectorPipeline.generate).parameters)
    assert params[1] == "topic"
