"""Build a timeline from an existing storyboard (asset references only)."""

from __future__ import annotations

from src.studio.models import Storyboard
from src.timeline.models import (
    Timeline,
    TimelineClip,
    TimelineTrack,
    TrackKind,
    default_tracks,
)


def _video_clips_from_storyboard(storyboard: Storyboard) -> list[TimelineClip]:
    cursor = 0.0
    video_clips: list[TimelineClip] = []
    for scene in storyboard.scenes:
        media_url = None
        poster_url = None
        asset_id = scene.video_asset_id or scene.image_asset_id
        if scene.video and scene.video.url:
            media_url = scene.video.url
            source_duration = float(
                scene.video.duration_seconds or scene.duration_seconds or 5.0
            )
        else:
            media_url = scene.image.url if scene.image else None
            source_duration = float(scene.duration_seconds or 5.0)
        if scene.image and scene.image.url:
            poster_url = scene.image.url

        duration = float(scene.duration_seconds or source_duration)
        video_clips.append(
            TimelineClip(
                label=scene.title or f"Scene {scene.id}",
                scene_id=scene.id,
                asset_id=asset_id,
                media_url=media_url,
                poster_url=poster_url,
                start_seconds=cursor,
                duration_seconds=duration,
                in_point=0.0,
                out_point=duration,
                source_duration=max(source_duration, duration),
            )
        )
        cursor += duration
    return video_clips


def build_timeline_from_storyboard(
    storyboard: Storyboard,
    *,
    existing: Timeline | None = None,
) -> Timeline:
    """Create or refresh the video track from storyboard scene media.

    Non-video tracks are preserved when ``existing`` is provided.
    Never generates media.
    """
    video_clips = _video_clips_from_storyboard(storyboard)

    if existing is None:
        tracks: list[TimelineTrack] = []
        for default in default_tracks():
            if default.kind == TrackKind.VIDEO:
                tracks.append(default.model_copy(update={"clips": video_clips}))
            else:
                tracks.append(default)
        return Timeline(project_id=storyboard.project_id, tracks=tracks)

    tracks = []
    replaced_video = False
    for track in existing.tracks:
        if track.kind == TrackKind.VIDEO:
            tracks.append(track.model_copy(update={"clips": video_clips}))
            replaced_video = True
        else:
            tracks.append(track)
    if not replaced_video:
        tracks.insert(
            0,
            TimelineTrack(kind=TrackKind.VIDEO, name="Video", clips=video_clips),
        )
    present = {t.kind for t in tracks}
    for default in default_tracks():
        if default.kind not in present:
            tracks.append(default)

    return existing.model_copy(
        update={"tracks": tracks, "project_id": storyboard.project_id}
    ).touch()
