"""Voice & Audio Studio orchestration — uses AudioRouter + timeline hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.audio.models import (
    AudioMode,
    AudioProject,
    AudioRequest,
    DubTrack,
    EmotionPreset,
    MixerState,
    MusicBed,
    MusicMood,
    NarrationClip,
    SfxCue,
    SubtitleCue,
    SubtitleFormat,
    VoiceProfile,
)
from src.audio.router import AudioRouter, get_audio_router
from src.audio.store import AudioProjectStore
from src.audio.subtitles import cues_from_narrations, export_subtitles
from src.models.memory import ProjectMemory
from src.studio.models import Storyboard
from src.timeline.models import Timeline, TimelineClip, TrackKind
from src.timeline.service import TimelineService


class AudioStudioService:
    """High-level Voice & Audio Studio API.

    All synthesis goes through :class:`AudioRouter` (provider-agnostic).
    Never imports vendor SDKs.
    """

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        store: AudioProjectStore | None = None,
        router: AudioRouter | None = None,
        timeline_service: TimelineService | None = None,
    ) -> None:
        root_path = Path(root) if root is not None else Path("artifacts") / "projects"
        self._store = store or AudioProjectStore(root=root_path)
        self._router = router or get_audio_router()
        self._timelines = timeline_service

    @property
    def store(self) -> AudioProjectStore:
        return self._store

    @property
    def router(self) -> AudioRouter:
        return self._router

    def load(self, project_id: str) -> AudioProject | None:
        return self._store.load(project_id)

    def save(self, project: AudioProject) -> AudioProject:
        board = project.touch()
        self._store.save(board)
        return board

    def get_or_create(
        self,
        project_id: str,
        *,
        memory: ProjectMemory | None = None,
        storyboard: Storyboard | None = None,
    ) -> AudioProject:
        existing = self.load(project_id)
        if existing is not None:
            return existing
        project = AudioProject(project_id=project_id)
        if memory is not None:
            project = self.seed_voices_from_memory(project, memory, persist=False)
        if storyboard is not None:
            project = self.draft_narrations_from_storyboard(
                project, storyboard, persist=False
            )
        return self.save(project)

    # ------------------------------------------------------------------
    # Voice profiles
    # ------------------------------------------------------------------

    def seed_voices_from_memory(
        self,
        project: AudioProject,
        memory: ProjectMemory,
        *,
        persist: bool = True,
    ) -> AudioProject:
        profiles = list(project.voice_profiles)
        existing_names = {p.character_name.casefold() for p in profiles}
        for char in memory.characters:
            if char.name.casefold() in existing_names:
                continue
            profiles.append(
                VoiceProfile(
                    character_id=char.id,
                    character_name=char.name,
                    label=f"{char.name} voice",
                    description=char.voice or char.personality or "",
                    language="en",
                )
            )
        project = project.model_copy(update={"voice_profiles": profiles})
        return self.save(project) if persist else project

    def upsert_voice_profile(
        self,
        project: AudioProject,
        profile: VoiceProfile,
        *,
        persist: bool = True,
    ) -> AudioProject:
        profiles = [p for p in project.voice_profiles if p.id != profile.id]
        profiles.append(profile)
        board = project.model_copy(update={"voice_profiles": profiles})
        return self.save(board) if persist else board

    def set_clone_ref(
        self,
        project: AudioProject,
        voice_id: str,
        clone_ref: str,
        *,
        persist: bool = True,
    ) -> AudioProject:
        """Attach a provider-agnostic clone reference (URL / asset key)."""
        profile = project.voice_by_id(voice_id)
        updated = profile.model_copy(update={"clone_ref": clone_ref})
        return self.upsert_voice_profile(project, updated, persist=persist)

    # ------------------------------------------------------------------
    # Narration
    # ------------------------------------------------------------------

    def draft_narrations_from_storyboard(
        self,
        project: AudioProject,
        storyboard: Storyboard,
        *,
        persist: bool = True,
    ) -> AudioProject:
        cursor = 0.0
        clips: list[NarrationClip] = []
        default_voice = project.voice_profiles[0].id if project.voice_profiles else None
        for scene in storyboard.scenes:
            text = scene.goal or scene.description or scene.title
            duration = float(scene.duration_seconds or 5.0)
            clips.append(
                NarrationClip(
                    scene_id=scene.id,
                    text=text,
                    voice_profile_id=default_voice,
                    start_seconds=cursor,
                    duration_seconds=duration,
                    status="draft",
                )
            )
            cursor += duration
        board = project.model_copy(update={"narrations": clips})
        return self.save(board) if persist else board

    def generate_narration(
        self,
        project: AudioProject,
        narration_id: str,
        *,
        persist: bool = True,
    ) -> AudioProject:
        clip = project.narration_by_id(narration_id)
        voice = None
        if clip.voice_profile_id:
            try:
                voice = project.voice_by_id(clip.voice_profile_id)
            except KeyError:
                voice = None
        request = AudioRequest(
            prompt=clip.text,
            text=clip.text,
            mode=AudioMode.CLONE if voice and voice.clone_ref else AudioMode.TTS,
            language=clip.language,
            voice_profile_id=clip.voice_profile_id,
            clone_ref=voice.clone_ref if voice else None,
            emotion=clip.emotion,
            speech_rate=clip.speech_rate,
            pitch=clip.pitch,
            duration=clip.duration_seconds or None,
            scene_id=clip.scene_id,
        )
        try:
            result = self._router.generate(request)
            updated = clip.model_copy(
                update={
                    "audio_url": result.url,
                    "duration_seconds": result.duration_seconds
                    or clip.duration_seconds,
                    "status": "generated",
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            updated = clip.model_copy(
                update={"status": "failed", "error": str(exc)}
            )
        narrations = [
            updated if n.id == narration_id else n for n in project.narrations
        ]
        board = project.model_copy(update={"narrations": narrations})
        return self.save(board) if persist else board

    def generate_all_narrations(
        self, project: AudioProject, *, persist: bool = True
    ) -> AudioProject:
        board = project
        for clip in list(board.narrations):
            board = self.generate_narration(board, clip.id, persist=False)
        return self.save(board) if persist else board

    def regenerate_scene_narration(
        self,
        project: AudioProject,
        scene_id: int,
        *,
        persist: bool = True,
    ) -> AudioProject:
        board = project
        for clip in board.narrations:
            if clip.scene_id == scene_id:
                board = self.generate_narration(board, clip.id, persist=False)
        return self.save(board) if persist else board

    # ------------------------------------------------------------------
    # Music / SFX
    # ------------------------------------------------------------------

    def add_music(
        self,
        project: AudioProject,
        *,
        mood: MusicMood = MusicMood.AMBIENT,
        duration: float = 30.0,
        generate: bool = True,
        persist: bool = True,
    ) -> AudioProject:
        bed = MusicBed(mood=mood, duration_seconds=duration, label=f"{mood.value} bed")
        if generate:
            result = self._router.generate(
                AudioRequest(
                    prompt=f"cinematic {mood.value} underscore",
                    text=f"cinematic {mood.value} underscore",
                    mode=AudioMode.MUSIC,
                    mood=mood,
                    duration=duration,
                )
            )
            bed = bed.model_copy(
                update={
                    "audio_url": result.url,
                    "duration_seconds": result.duration_seconds or duration,
                    "status": "generated",
                }
            )
        music = list(project.music) + [bed]
        board = project.model_copy(update={"music": music})
        return self.save(board) if persist else board

    def add_sfx(
        self,
        project: AudioProject,
        *,
        description: str,
        kind: str = "scene",
        scene_id: int | None = None,
        start_seconds: float = 0.0,
        generate: bool = True,
        persist: bool = True,
    ) -> AudioProject:
        cue = SfxCue(
            label=description[:48] or "SFX",
            kind="ambient" if kind == "ambient" else "scene",
            scene_id=scene_id,
            description=description,
            start_seconds=start_seconds,
        )
        if generate:
            result = self._router.generate(
                AudioRequest(
                    prompt=description,
                    text=description,
                    mode=AudioMode.SFX,
                    duration=cue.duration_seconds,
                    scene_id=scene_id,
                )
            )
            cue = cue.model_copy(
                update={
                    "audio_url": result.url,
                    "duration_seconds": result.duration_seconds or cue.duration_seconds,
                    "status": "generated",
                }
            )
        sfx = list(project.sfx) + [cue]
        board = project.model_copy(update={"sfx": sfx})
        return self.save(board) if persist else board

    # ------------------------------------------------------------------
    # Subtitles
    # ------------------------------------------------------------------

    def auto_generate_subtitles(
        self,
        project: AudioProject,
        *,
        language: str | None = None,
        persist: bool = True,
    ) -> AudioProject:
        cues = cues_from_narrations(project.narrations, language=language)
        # Preserve manually edited cues in other languages.
        keep = [
            cue
            for cue in project.subtitles
            if language is not None and cue.language != language
        ]
        board = project.model_copy(update={"subtitles": keep + cues})
        return self.save(board) if persist else board

    def update_subtitle(
        self,
        project: AudioProject,
        cue_id: str,
        *,
        text: str | None = None,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        language: str | None = None,
        persist: bool = True,
    ) -> AudioProject:
        updated: list[SubtitleCue] = []
        found = False
        for cue in project.subtitles:
            if cue.id != cue_id:
                updated.append(cue)
                continue
            found = True
            patch: dict[str, Any] = {}
            if text is not None:
                patch["text"] = text
            if start_seconds is not None:
                patch["start_seconds"] = start_seconds
            if end_seconds is not None:
                patch["end_seconds"] = end_seconds
            if language is not None:
                patch["language"] = language
            updated.append(cue.model_copy(update=patch))
        if not found:
            raise KeyError(f"Subtitle cue {cue_id!r} not found")
        board = project.model_copy(update={"subtitles": updated})
        return self.save(board) if persist else board

    def export_subtitle_file(
        self,
        project: AudioProject,
        *,
        fmt: SubtitleFormat = SubtitleFormat.SRT,
        language: str | None = None,
    ) -> str:
        return export_subtitles(project.subtitles, fmt=fmt, language=language)

    # ------------------------------------------------------------------
    # Dubbing
    # ------------------------------------------------------------------

    def add_dub_track(
        self,
        project: AudioProject,
        *,
        language: str,
        voice_map: dict[str, str] | None = None,
        label: str | None = None,
        persist: bool = True,
    ) -> AudioProject:
        track = DubTrack(
            language=language,
            label=label or f"Dub {language}",
            voice_map=dict(voice_map or {}),
        )
        # Clone narration texts into language-tagged drafts mapped to voices.
        narration_ids: list[str] = []
        narrations = list(project.narrations)
        for source in project.narrations:
            mapped_voice = None
            if source.voice_profile_id and voice_map:
                # Prefer explicit character mapping via profile character name.
                try:
                    profile = project.voice_by_id(source.voice_profile_id)
                    mapped_voice = voice_map.get(profile.character_name) or voice_map.get(
                        profile.character_id or ""
                    )
                except KeyError:
                    mapped_voice = None
            clone = source.model_copy(
                update={
                    "language": language,
                    "voice_profile_id": mapped_voice or source.voice_profile_id,
                    "audio_url": None,
                    "status": "draft",
                    "error": None,
                }
            )
            from src.audio.models import _new_id

            clone = clone.model_copy(update={"id": _new_id(f"narr_{language}")})
            narrations.append(clone)
            narration_ids.append(clone.id)
        track = track.model_copy(update={"narration_ids": narration_ids})
        board = project.model_copy(
            update={
                "dubs": list(project.dubs) + [track],
                "narrations": narrations,
            }
        )
        return self.save(board) if persist else board

    def sync_dub_to_timeline_times(
        self,
        project: AudioProject,
        dub_id: str,
        *,
        persist: bool = True,
    ) -> AudioProject:
        """Align dub narration start times with the matching scene base language."""
        dub = next((d for d in project.dubs if d.id == dub_id), None)
        if dub is None:
            raise KeyError(f"Dub track {dub_id!r} not found")
        base_by_scene = {
            n.scene_id: n
            for n in project.narrations
            if n.scene_id is not None and n.id not in dub.narration_ids
        }
        narrations: list[NarrationClip] = []
        for clip in project.narrations:
            if clip.id not in dub.narration_ids:
                narrations.append(clip)
                continue
            base = base_by_scene.get(clip.scene_id) if clip.scene_id else None
            if base is None:
                narrations.append(clip)
                continue
            narrations.append(
                clip.model_copy(
                    update={
                        "start_seconds": base.start_seconds,
                        "duration_seconds": base.duration_seconds,
                    }
                )
            )
        dubs = [
            d.model_copy(update={"synced": True}) if d.id == dub_id else d
            for d in project.dubs
        ]
        board = project.model_copy(update={"narrations": narrations, "dubs": dubs})
        return self.save(board) if persist else board

    # ------------------------------------------------------------------
    # Mixer
    # ------------------------------------------------------------------

    def set_mixer(
        self,
        project: AudioProject,
        mixer: MixerState,
        *,
        persist: bool = True,
    ) -> AudioProject:
        board = project.model_copy(update={"mixer": mixer})
        return self.save(board) if persist else board

    # ------------------------------------------------------------------
    # Export → timeline
    # ------------------------------------------------------------------

    def export_to_timeline(
        self,
        project: AudioProject,
        timeline: Timeline,
        *,
        persist_timeline: bool = True,
    ) -> Timeline:
        """Place generated audio/subtitle assets onto timeline tracks.

        References existing URLs only — does not regenerate media.
        """
        if self._timelines is None:
            raise RuntimeError("TimelineService is required for audio export")

        def _replace_track_clips(
            board: Timeline, kind: TrackKind, clips: list[TimelineClip]
        ) -> Timeline:
            tracks = []
            for track in board.tracks:
                if track.kind == kind:
                    tracks.append(track.model_copy(update={"clips": clips}))
                else:
                    tracks.append(track)
            return board.model_copy(update={"tracks": tracks})

        voice_clips = [
            TimelineClip(
                label=f"Narration {n.scene_id or n.id}",
                scene_id=n.scene_id,
                media_url=n.audio_url,
                start_seconds=n.start_seconds,
                duration_seconds=max(n.duration_seconds, 0.1),
                in_point=0.0,
                out_point=max(n.duration_seconds, 0.1),
                source_duration=max(n.duration_seconds, 0.1),
                text=n.text,
                muted=project.mixer.muted_voice,
            )
            for n in project.narrations
            if n.audio_url and n.language == "en"
        ]
        music_clips = [
            TimelineClip(
                label=m.label,
                media_url=m.audio_url,
                start_seconds=m.start_seconds,
                duration_seconds=m.duration_seconds,
                in_point=0.0,
                out_point=m.duration_seconds,
                source_duration=m.duration_seconds,
                muted=project.mixer.muted_music,
            )
            for m in project.music
            if m.audio_url
        ]
        sfx_clips = [
            TimelineClip(
                label=s.label,
                scene_id=s.scene_id,
                media_url=s.audio_url,
                start_seconds=s.start_seconds,
                duration_seconds=s.duration_seconds,
                in_point=0.0,
                out_point=s.duration_seconds,
                source_duration=s.duration_seconds,
                muted=project.mixer.muted_sfx,
            )
            for s in project.sfx
            if s.audio_url
        ]
        sub_clips = [
            TimelineClip(
                label=f"Sub {c.language}",
                scene_id=c.scene_id,
                start_seconds=c.start_seconds,
                duration_seconds=max(c.end_seconds - c.start_seconds, 0.1),
                in_point=0.0,
                out_point=max(c.end_seconds - c.start_seconds, 0.1),
                source_duration=max(c.end_seconds - c.start_seconds, 0.1),
                text=c.text,
            )
            for c in project.subtitles
        ]

        board = timeline
        board = _replace_track_clips(board, TrackKind.VOICE, voice_clips)
        board = _replace_track_clips(board, TrackKind.MUSIC, music_clips)
        board = _replace_track_clips(board, TrackKind.SFX, sfx_clips)
        board = _replace_track_clips(board, TrackKind.SUBTITLES, sub_clips)
        board = board.model_copy(
            update={
                "metadata": {
                    **board.metadata,
                    "audio_mixer": project.mixer.model_dump(mode="json"),
                    "audio_version": project.version,
                }
            }
        )
        if persist_timeline:
            return self._timelines.save(board)
        return board.touch()
