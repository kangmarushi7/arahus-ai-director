"""Domain models for Voice & Audio Studio (provider-agnostic)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from src.media.request import GenerationProfileName, MediaRequest, QualityMode
from src.models.base import StrictModel


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class EmotionPreset(str, Enum):
    NEUTRAL = "neutral"
    WARM = "warm"
    TENSE = "tense"
    SOLEMN = "solemn"
    URGENT = "urgent"
    JOYFUL = "joyful"
    WHISPER = "whisper"


class AudioMode(str, Enum):
    TTS = "tts"
    CLONE = "clone"
    MUSIC = "music"
    SFX = "sfx"


class MusicMood(str, Enum):
    EPIC = "epic"
    SOMBER = "somber"
    TENSE = "tense"
    HOPEFUL = "hopeful"
    MYSTERIOUS = "mysterious"
    TRIUMPHANT = "triumphant"
    AMBIENT = "ambient"


class SubtitleFormat(str, Enum):
    SRT = "srt"
    VTT = "vtt"


# ---------------------------------------------------------------------------
# Voice profiles
# ---------------------------------------------------------------------------


class VoiceProfile(StrictModel):
    """Character voice identity — no vendor IDs required."""

    id: str = Field(default_factory=lambda: _new_id("voice"))
    character_id: str | None = None
    character_name: str = ""
    label: str = ""
    description: str = ""
    language: str = "en"
    emotion: EmotionPreset = EmotionPreset.NEUTRAL
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    # Provider-agnostic clone reference (URL or opaque asset key).
    clone_ref: str | None = None
    provider_hint: str | None = None
    asset_id: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "character_id",
        "clone_ref",
        "provider_hint",
        mode="before",
    )
    @classmethod
    def _normalize_optional(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return " ".join(value.split()) or None
        return value

    @field_validator("character_name", "label", "description", "language", mode="before")
    @classmethod
    def _normalize_required_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


# ---------------------------------------------------------------------------
# Generation I/O (router layer)
# ---------------------------------------------------------------------------


class AudioRequest(MediaRequest):
    """Input to :meth:`~src.audio.router.AudioRouter.generate`."""

    text: str = ""
    mode: AudioMode = AudioMode.TTS
    language: str = "en"
    voice_profile_id: str | None = None
    clone_ref: str | None = None
    emotion: EmotionPreset | None = None
    speech_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch: float | None = Field(default=None, ge=-12.0, le=12.0)
    mood: MusicMood | None = None
    duration: float | None = Field(default=None, ge=0.1)
    scene_id: int | None = Field(default=None, ge=1)

    @field_validator("text", "language", "voice_profile_id", "clone_ref", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


class AudioGenerationParams(StrictModel):
    model_key: str
    model_id: str
    provider: str
    quality: QualityMode = "production"
    profile: GenerationProfileName = "production"
    mode: AudioMode = AudioMode.TTS
    sample_rate: int = Field(default=24000, ge=8000)
    format: str = "wav"
    cost_per_second: float = Field(default=0.0, ge=0.0)


class AudioResult(StrictModel):
    """Generated or stubbed audio asset reference (never embeds vendor payloads)."""

    prompt: str = ""
    url: str | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    format: str = "wav"
    sample_rate: int = Field(default=24000, ge=8000)
    provider: str = "stub"
    model_id: str = ""
    asset_id: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Project document (persisted studio state)
# ---------------------------------------------------------------------------


class VolumeKeyframe(StrictModel):
    time_seconds: float = Field(ge=0.0)
    volume: float = Field(ge=0.0, le=2.0, default=1.0)


class NarrationClip(StrictModel):
    id: str = Field(default_factory=lambda: _new_id("narr"))
    scene_id: int | None = Field(default=None, ge=1)
    text: str = ""
    language: str = "en"
    voice_profile_id: str | None = None
    emotion: EmotionPreset = EmotionPreset.NEUTRAL
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    audio_url: str | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    start_seconds: float = Field(default=0.0, ge=0.0)
    status: Literal["draft", "generated", "failed"] = "draft"
    error: str | None = None


class MusicBed(StrictModel):
    id: str = Field(default_factory=lambda: _new_id("music"))
    label: str = "Background"
    mood: MusicMood = MusicMood.AMBIENT
    audio_url: str | None = None
    start_seconds: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(default=30.0, ge=0.1)
    volume: float = Field(default=0.35, ge=0.0, le=2.0)
    fade_in_seconds: float = Field(default=1.5, ge=0.0)
    fade_out_seconds: float = Field(default=2.0, ge=0.0)
    automation: list[VolumeKeyframe] = Field(default_factory=list)
    status: Literal["draft", "generated", "failed"] = "draft"


class SfxCue(StrictModel):
    id: str = Field(default_factory=lambda: _new_id("sfx"))
    label: str = ""
    kind: Literal["ambient", "scene"] = "scene"
    scene_id: int | None = Field(default=None, ge=1)
    description: str = ""
    audio_url: str | None = None
    start_seconds: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(default=2.0, ge=0.1)
    volume: float = Field(default=0.8, ge=0.0, le=2.0)
    status: Literal["draft", "generated", "failed"] = "draft"


class SubtitleCue(StrictModel):
    id: str = Field(default_factory=lambda: _new_id("sub"))
    scene_id: int | None = Field(default=None, ge=1)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    text: str = ""
    language: str = "en"


class DubTrack(StrictModel):
    id: str = Field(default_factory=lambda: _new_id("dub"))
    language: str = "en"
    label: str = ""
    voice_map: dict[str, str] = Field(
        default_factory=dict
    )  # character_id/name → voice_profile_id
    narration_ids: list[str] = Field(default_factory=list)
    synced: bool = False


class MixerState(StrictModel):
    voice: float = Field(default=1.0, ge=0.0, le=2.0)
    music: float = Field(default=0.35, ge=0.0, le=2.0)
    sfx: float = Field(default=0.8, ge=0.0, le=2.0)
    master: float = Field(default=1.0, ge=0.0, le=2.0)
    muted_voice: bool = False
    muted_music: bool = False
    muted_sfx: bool = False


class AudioProject(StrictModel):
    """Persisted Voice & Audio Studio document per project."""

    project_id: str
    version: int = Field(default=1, ge=1)
    voice_profiles: list[VoiceProfile] = Field(default_factory=list)
    narrations: list[NarrationClip] = Field(default_factory=list)
    music: list[MusicBed] = Field(default_factory=list)
    sfx: list[SfxCue] = Field(default_factory=list)
    subtitles: list[SubtitleCue] = Field(default_factory=list)
    dubs: list[DubTrack] = Field(default_factory=list)
    mixer: MixerState = Field(default_factory=MixerState)
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> AudioProject:
        return self.model_copy(
            update={"updated_at": _utc_iso(), "version": self.version + 1}
        )

    def voice_by_id(self, voice_id: str) -> VoiceProfile:
        for profile in self.voice_profiles:
            if profile.id == voice_id:
                return profile
        raise KeyError(f"Voice profile {voice_id!r} not found")

    def narration_by_id(self, narration_id: str) -> NarrationClip:
        for clip in self.narrations:
            if clip.id == narration_id:
                return clip
        raise KeyError(f"Narration {narration_id!r} not found")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioProject:
        return cls.model_validate(data)
