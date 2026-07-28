"""Sprint 6.5 — Voice & Audio Studio integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import (
    get_audio_studio,
    get_copilot_service,
    get_project_service,
    get_timeline_service,
    reset_api_singletons,
)
from src.api.services.projects import ProjectService
from src.audio.models import AudioMode, AudioRequest
from src.audio.router import AudioRouter
from src.audio.service import AudioStudioService
from src.audio.store import AudioProjectStore
from src.copilot.service import CopilotService
from src.memory.store import ProjectMemoryStore
from src.models.image import ImageResult
from src.models.memory import CharacterBible, ProjectMemory
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
    copilot = CopilotService(
        root=tmp_path,
        studio=service.studio,
        memory_store=service.memory_store,
    )
    app = create_app(enable_cors=False)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_timeline_service] = lambda: timelines
    app.dependency_overrides[get_audio_studio] = lambda: audio
    app.dependency_overrides[get_copilot_service] = lambda: copilot

    class _FakePipeline:
        def generate(self, topic: str, progress_callback=None) -> PipelineResult:
            return _fake_pipeline_result(topic)

    monkeypatch.setattr(
        "src.api.routes.projects.build_pipeline",
        lambda: _FakePipeline(),
    )

    with TestClient(app) as client:
        yield client, service, audio, timelines

    app.dependency_overrides.clear()
    reset_api_singletons()


def _seed(client: TestClient, service: ProjectService) -> str:
    project_id = client.post("/projects", json={"topic": "Audio Alps"}).json()["id"]
    client.post(f"/projects/{project_id}/generate?wait=true", json={})
    service.memory_store.save(
        ProjectMemory(
            project_id=project_id,
            topic="Audio Alps",
            characters=[
                CharacterBible(
                    id="napoleon",
                    asset_id=1,
                    name="Napoleon",
                    voice="commanding baritone",
                )
            ],
        )
    )
    return project_id


def test_stub_router_never_imports_vendor() -> None:
    router = AudioRouter.from_yaml()
    assert "stub" in router.providers
    result = router.generate(
        AudioRequest(
            prompt="At dawn we cross the pass.",
            text="At dawn we cross the pass.",
            mode=AudioMode.TTS,
            emotion=None,
        )
    )
    assert result.url
    assert result.provider == "stub"
    assert result.metadata.get("stub") is True


def test_audio_studio_flow(api_client) -> None:
    client, service, _, timelines = api_client
    project_id = _seed(client, service)

    audio = client.get(f"/projects/{project_id}/audio")
    assert audio.status_code == 200
    body = audio.json()
    assert body["project_id"] == project_id
    assert len(body["voice_profiles"]) >= 1
    assert len(body["narrations"]) == 4

    voice_id = body["voice_profiles"][0]["id"]
    cloned = client.post(
        f"/projects/{project_id}/audio/voices/{voice_id}/clone",
        json={"clone_ref": "asset://sample-voice-1"},
    )
    assert cloned.status_code == 200
    assert cloned.json()["voice_profiles"][0]["clone_ref"] == "asset://sample-voice-1"

    narrated = client.post(f"/projects/{project_id}/audio/narration/generate")
    assert narrated.status_code == 200
    assert all(n["status"] == "generated" for n in narrated.json()["narrations"])

    regen = client.post(
        f"/projects/{project_id}/audio/narration/scenes/2/regenerate"
    )
    assert regen.status_code == 200

    music = client.post(
        f"/projects/{project_id}/audio/music",
        json={"mood": "epic", "duration": 20},
    )
    assert music.status_code == 200
    assert music.json()["music"][0]["mood"] == "epic"
    assert music.json()["music"][0]["fade_in_seconds"] > 0

    sfx = client.post(
        f"/projects/{project_id}/audio/sfx",
        json={"description": "wind over alpine ridge", "kind": "ambient"},
    )
    assert sfx.status_code == 200

    subs = client.post(f"/projects/{project_id}/audio/subtitles/auto")
    assert subs.status_code == 200
    assert len(subs.json()["subtitles"]) >= 4
    cue_id = subs.json()["subtitles"][0]["id"]
    patched = client.patch(
        f"/projects/{project_id}/audio/subtitles/{cue_id}",
        json={"text": "Edited caption"},
    )
    assert patched.status_code == 200
    assert patched.json()["subtitles"][0]["text"] == "Edited caption"

    srt = client.get(f"/projects/{project_id}/audio/subtitles/export?format=srt")
    assert srt.status_code == 200
    assert "-->" in srt.text
    vtt = client.get(f"/projects/{project_id}/audio/subtitles/export?format=vtt")
    assert vtt.status_code == 200
    assert vtt.text.startswith("WEBVTT")

    dub = client.post(
        f"/projects/{project_id}/audio/dubs",
        json={"language": "fr", "voice_map": {"Napoleon": voice_id}},
    )
    assert dub.status_code == 200
    dub_id = dub.json()["dubs"][0]["id"]
    synced = client.post(f"/projects/{project_id}/audio/dubs/{dub_id}/sync")
    assert synced.status_code == 200
    assert synced.json()["dubs"][0]["synced"] is True

    mixer = client.put(
        f"/projects/{project_id}/audio/mixer",
        json={"voice": 1.0, "music": 0.25, "sfx": 0.7, "master": 0.9},
    )
    assert mixer.status_code == 200
    assert mixer.json()["mixer"]["music"] == 0.25

    client.post(f"/projects/{project_id}/timeline/sync", json={})
    exported = client.post(f"/projects/{project_id}/audio/export-timeline")
    assert exported.status_code == 200
    timeline = exported.json()["timeline"]
    kinds = {t["kind"]: t for t in timeline["tracks"]}
    assert kinds["voice"]["clips"]
    assert kinds["music"]["clips"]
    assert kinds["sfx"]["clips"]
    assert kinds["subtitles"]["clips"]
    assert timeline["metadata"]["audio_mixer"]["master"] == 0.9
    assert (service.root / project_id / "audio.json").is_file()


def test_audio_openapi_and_health(api_client) -> None:
    client, _, _, _ = api_client
    paths = client.get("/openapi.json").json()["paths"]
    assert "/projects/{project_id}/audio" in paths
    assert "/projects/{project_id}/audio/export-timeline" in paths
    health = client.get("/audio/providers/health")
    assert health.status_code == 200
    assert "stub" in health.json()


def test_pipeline_unchanged() -> None:
    import inspect

    from src.pipeline import DirectorPipeline

    assert list(inspect.signature(DirectorPipeline.generate).parameters)[1] == "topic"
