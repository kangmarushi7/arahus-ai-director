"""Voice & Audio Studio REST routes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.api.deps import (
    get_audio_studio,
    get_project_service,
    get_timeline_service,
)
from src.api.services.projects import ProjectService
from src.audio.models import (
    EmotionPreset,
    MixerState,
    MusicMood,
    SubtitleFormat,
    VoiceProfile,
)
from src.audio.service import AudioStudioService
from src.timeline.service import TimelineService

router = APIRouter(tags=["audio"])


class VoiceUpsertRequest(BaseModel):
    id: str | None = None
    character_id: str | None = None
    character_name: str = ""
    label: str = ""
    description: str = ""
    language: str = "en"
    emotion: str = "neutral"
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    clone_ref: str | None = None


class CloneRefRequest(BaseModel):
    clone_ref: str = Field(min_length=1)


class MusicRequest(BaseModel):
    mood: str = "ambient"
    duration: float = Field(default=30.0, ge=1.0)
    generate: bool = True


class SfxRequest(BaseModel):
    description: str = Field(min_length=1)
    kind: Literal["ambient", "scene"] = "scene"
    scene_id: int | None = Field(default=None, ge=1)
    start_seconds: float = Field(default=0.0, ge=0.0)
    generate: bool = True


class SubtitlePatchRequest(BaseModel):
    text: str | None = None
    start_seconds: float | None = Field(default=None, ge=0.0)
    end_seconds: float | None = Field(default=None, gt=0.0)
    language: str | None = None


class DubRequest(BaseModel):
    language: str = Field(min_length=2, max_length=16)
    label: str | None = None
    voice_map: dict[str, str] = Field(default_factory=dict)


class MixerRequest(BaseModel):
    voice: float = Field(default=1.0, ge=0.0, le=2.0)
    music: float = Field(default=0.35, ge=0.0, le=2.0)
    sfx: float = Field(default=0.8, ge=0.0, le=2.0)
    master: float = Field(default=1.0, ge=0.0, le=2.0)
    muted_voice: bool = False
    muted_music: bool = False
    muted_sfx: bool = False


def _project_audio(
    project_id: str,
    projects: ProjectService,
    audio: AudioStudioService,
) -> Any:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    memory = projects.memory_store.load(project_id)
    board = projects.studio.load(project_id)
    return audio.get_or_create(project_id, memory=memory, storyboard=board)


@router.get("/projects/{project_id}/audio")
def get_audio_project(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    return _project_audio(project_id, projects, audio).to_dict()


@router.post("/projects/{project_id}/audio/voices")
def upsert_voice(
    project_id: str,
    body: VoiceUpsertRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    try:
        emotion = EmotionPreset(body.emotion)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = VoiceProfile(
        id=body.id or VoiceProfile().id,
        character_id=body.character_id,
        character_name=body.character_name,
        label=body.label or body.character_name or "Voice",
        description=body.description,
        language=body.language,
        emotion=emotion,
        speech_rate=body.speech_rate,
        pitch=body.pitch,
        clone_ref=body.clone_ref,
    )
    return audio.upsert_voice_profile(project, profile).to_dict()


@router.post("/projects/{project_id}/audio/voices/{voice_id}/clone")
def set_clone_ref(
    project_id: str,
    voice_id: str,
    body: CloneRefRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    try:
        return audio.set_clone_ref(project, voice_id, body.clone_ref).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/audio/narration/draft")
def draft_narration(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    board = projects.studio.load(project_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Storyboard required")
    return audio.draft_narrations_from_storyboard(project, board).to_dict()


@router.post("/projects/{project_id}/audio/narration/generate")
def generate_all_narration(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    return audio.generate_all_narrations(project).to_dict()


@router.post("/projects/{project_id}/audio/narration/scenes/{scene_id}/regenerate")
def regenerate_scene_narration(
    project_id: str,
    scene_id: int,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    return audio.regenerate_scene_narration(project, scene_id).to_dict()


@router.post("/projects/{project_id}/audio/music")
def add_music(
    project_id: str,
    body: MusicRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    try:
        mood = MusicMood(body.mood)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return audio.add_music(
        project, mood=mood, duration=body.duration, generate=body.generate
    ).to_dict()


@router.post("/projects/{project_id}/audio/sfx")
def add_sfx(
    project_id: str,
    body: SfxRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    return audio.add_sfx(
        project,
        description=body.description,
        kind=body.kind,
        scene_id=body.scene_id,
        start_seconds=body.start_seconds,
        generate=body.generate,
    ).to_dict()


@router.post("/projects/{project_id}/audio/subtitles/auto")
def auto_subtitles(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
    language: str | None = Query(default=None),
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    return audio.auto_generate_subtitles(project, language=language).to_dict()


@router.patch("/projects/{project_id}/audio/subtitles/{cue_id}")
def patch_subtitle(
    project_id: str,
    cue_id: str,
    body: SubtitlePatchRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    try:
        return audio.update_subtitle(
            project,
            cue_id,
            text=body.text,
            start_seconds=body.start_seconds,
            end_seconds=body.end_seconds,
            language=body.language,
        ).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/audio/subtitles/export")
def export_subtitles_file(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
    format: Literal["srt", "vtt"] = Query(default="srt"),
    language: str | None = Query(default=None),
) -> PlainTextResponse:
    project = _project_audio(project_id, projects, audio)
    text = audio.export_subtitle_file(
        project,
        fmt=SubtitleFormat(format),
        language=language,
    )
    media = "text/vtt" if format == "vtt" else "application/x-subrip"
    return PlainTextResponse(text, media_type=media)


@router.post("/projects/{project_id}/audio/dubs")
def add_dub(
    project_id: str,
    body: DubRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    return audio.add_dub_track(
        project,
        language=body.language,
        voice_map=body.voice_map,
        label=body.label,
    ).to_dict()


@router.post("/projects/{project_id}/audio/dubs/{dub_id}/sync")
def sync_dub(
    project_id: str,
    dub_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    try:
        return audio.sync_dub_to_timeline_times(project, dub_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/projects/{project_id}/audio/mixer")
def set_mixer(
    project_id: str,
    body: MixerRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    mixer = MixerState(**body.model_dump())
    return audio.set_mixer(project, mixer).to_dict()


@router.post("/projects/{project_id}/audio/export-timeline")
def export_audio_timeline(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
    timelines: Annotated[TimelineService, Depends(get_timeline_service)],
) -> dict[str, Any]:
    project = _project_audio(project_id, projects, audio)
    board = projects.studio.load(project_id)
    timeline = timelines.get_or_create(project_id, storyboard=board)
    # Ensure service has timeline dependency for this request.
    audio._timelines = timelines
    updated = audio.export_to_timeline(project, timeline, persist_timeline=True)
    return {
        "audio": project.to_dict(),
        "timeline": updated.to_dict(),
    }


@router.get("/audio/providers/health")
def audio_providers_health(
    audio: Annotated[AudioStudioService, Depends(get_audio_studio)],
) -> dict[str, Any]:
    return {
        provider: backend.healthcheck()
        for provider, backend in audio.router.providers.items()
    }
