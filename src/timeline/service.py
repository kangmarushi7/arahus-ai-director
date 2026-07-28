"""Timeline editing service — non-destructive ops over asset references."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from src.studio.models import Storyboard
from src.timeline.builder import build_timeline_from_storyboard
from src.timeline.models import (
    ExportAspect,
    ExportFormat,
    ExportJob,
    ExportJobStatus,
    Timeline,
    TimelineClip,
    TransitionType,
    TrackKind,
    _new_id,
)
from src.timeline.store import TimelineStore


def _pack_track_clips(clips: list[TimelineClip]) -> list[TimelineClip]:
    """Re-sequence start times in the given order so clips abut without gaps."""
    cursor = 0.0
    packed: list[TimelineClip] = []
    for clip in clips:
        packed.append(clip.model_copy(update={"start_seconds": cursor}))
        cursor += clip.duration_seconds
    return packed


class TimelineService:
    """Edit timeline documents without regenerating media."""

    def __init__(self, store: TimelineStore | None = None) -> None:
        self._store = store or TimelineStore()

    @property
    def store(self) -> TimelineStore:
        return self._store

    def load(self, project_id: str) -> Timeline | None:
        return self._store.load(project_id)

    def save(self, timeline: Timeline) -> Timeline:
        board = timeline.touch()
        self._store.save(board)
        return board

    def get_or_create(
        self,
        project_id: str,
        storyboard: Storyboard | None = None,
    ) -> Timeline:
        existing = self.load(project_id)
        if existing is not None:
            return existing
        if storyboard is None:
            from src.timeline.models import default_tracks

            timeline = Timeline(project_id=project_id, tracks=default_tracks())
            return self.save(timeline)
        timeline = build_timeline_from_storyboard(storyboard)
        return self.save(timeline)

    def sync_from_storyboard(
        self,
        project_id: str,
        storyboard: Storyboard,
        *,
        preserve_non_video: bool = True,
    ) -> Timeline:
        existing = self.load(project_id) if preserve_non_video else None
        timeline = build_timeline_from_storyboard(storyboard, existing=existing)
        return self.save(timeline)

    # ------------------------------------------------------------------
    # Clip placement
    # ------------------------------------------------------------------

    def move_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        start_seconds: float,
        track_id: str | None = None,
        persist: bool = True,
    ) -> Timeline:
        track, clip = timeline.find_clip(clip_id)
        target = timeline.track_by_id(track_id) if track_id else track
        if target.locked:
            raise ValueError(f"Track {target.name} is locked")

        tracks = []
        for item in timeline.tracks:
            if item.id == track.id and item.id == target.id:
                clips = [
                    c.model_copy(update={"start_seconds": max(0.0, start_seconds)})
                    if c.id == clip_id
                    else c
                    for c in item.clips
                ]
                tracks.append(item.model_copy(update={"clips": clips}))
            elif item.id == track.id:
                tracks.append(
                    item.model_copy(
                        update={"clips": [c for c in item.clips if c.id != clip_id]}
                    )
                )
            elif item.id == target.id:
                moved = clip.model_copy(
                    update={"start_seconds": max(0.0, start_seconds)}
                )
                tracks.append(
                    item.model_copy(update={"clips": list(item.clips) + [moved]})
                )
            else:
                tracks.append(item)
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    def resize_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        duration_seconds: float,
        persist: bool = True,
    ) -> Timeline:
        if duration_seconds <= 0.05:
            raise ValueError("duration_seconds must be > 0.05")
        track, clip = timeline.find_clip(clip_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        # Non-destructive: adjust out_point within source when possible.
        new_out = min(clip.in_point + duration_seconds, clip.source_duration)
        new_duration = max(0.05, new_out - clip.in_point)
        return self._replace_clip(
            timeline,
            clip_id,
            clip.model_copy(
                update={
                    "duration_seconds": new_duration,
                    "out_point": clip.in_point + new_duration,
                }
            ),
            persist=persist,
        )

    def reorder_clips(
        self,
        timeline: Timeline,
        track_id: str,
        clip_ids: list[str],
        *,
        persist: bool = True,
    ) -> Timeline:
        track = timeline.track_by_id(track_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        by_id = {c.id: c for c in track.clips}
        if set(clip_ids) != set(by_id):
            raise ValueError("clip_ids must be a permutation of track clips")
        ordered = [by_id[cid] for cid in clip_ids]
        packed = _pack_track_clips(ordered)
        tracks = [
            t.model_copy(update={"clips": packed}) if t.id == track_id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    # ------------------------------------------------------------------
    # Edit ops
    # ------------------------------------------------------------------

    def trim_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        in_point: float | None = None,
        out_point: float | None = None,
        persist: bool = True,
    ) -> Timeline:
        track, clip = timeline.find_clip(clip_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        new_in = clip.in_point if in_point is None else max(0.0, in_point)
        new_out = (
            clip.out_point
            if out_point is None
            else min(clip.source_duration, max(new_in + 0.05, out_point))
        )
        if new_out <= new_in:
            raise ValueError("out_point must be greater than in_point")
        duration = new_out - new_in
        return self._replace_clip(
            timeline,
            clip_id,
            clip.model_copy(
                update={
                    "in_point": new_in,
                    "out_point": new_out,
                    "duration_seconds": duration,
                }
            ),
            persist=persist,
        )

    def split_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        at_seconds: float,
        persist: bool = True,
    ) -> Timeline:
        """Split clip at absolute timeline time ``at_seconds``."""
        track, clip = timeline.find_clip(clip_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        if not (clip.start_seconds < at_seconds < clip.end_seconds):
            raise ValueError("Split point must be inside the clip")
        offset = at_seconds - clip.start_seconds
        left_dur = offset
        right_dur = clip.duration_seconds - offset
        if left_dur < 0.05 or right_dur < 0.05:
            raise ValueError("Split would create a clip shorter than 0.05s")

        left = clip.model_copy(
            update={
                "duration_seconds": left_dur,
                "out_point": clip.in_point + left_dur,
            }
        )
        right = clip.model_copy(
            update={
                "id": _new_id("clip"),
                "start_seconds": at_seconds,
                "duration_seconds": right_dur,
                "in_point": clip.in_point + left_dur,
                "out_point": clip.out_point,
                "label": f"{clip.label} (B)" if clip.label else "Clip B",
            }
        )
        new_clips: list[TimelineClip] = []
        for item in track.clips:
            if item.id == clip_id:
                new_clips.extend([left, right])
            else:
                new_clips.append(item)
        tracks = [
            t.model_copy(update={"clips": new_clips}) if t.id == track.id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    def merge_clips(
        self,
        timeline: Timeline,
        clip_ids: list[str],
        *,
        persist: bool = True,
    ) -> Timeline:
        if len(clip_ids) < 2:
            raise ValueError("Need at least two clips to merge")
        located = [timeline.find_clip(cid) for cid in clip_ids]
        track_ids = {t.id for t, _ in located}
        if len(track_ids) != 1:
            raise ValueError("Clips must be on the same track")
        track = located[0][0]
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        clips = sorted((c for _, c in located), key=lambda c: c.start_seconds)
        # Adjacent check (small tolerance)
        for a, b in zip(clips, clips[1:]):
            if abs(a.end_seconds - b.start_seconds) > 0.05:
                raise ValueError("Only adjacent clips can be merged")
        first = clips[0]
        last = clips[-1]
        merged = first.model_copy(
            update={
                "duration_seconds": last.end_seconds - first.start_seconds,
                "out_point": first.in_point
                + (last.end_seconds - first.start_seconds),
                "label": first.label or "Merged",
            }
        )
        remove = set(clip_ids)
        new_clips = []
        inserted = False
        for item in track.clips:
            if item.id in remove:
                if not inserted:
                    new_clips.append(merged)
                    inserted = True
                continue
            new_clips.append(item)
        tracks = [
            t.model_copy(update={"clips": new_clips}) if t.id == track.id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    def delete_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        persist: bool = True,
        close_gaps: bool = False,
    ) -> Timeline:
        track, _ = timeline.find_clip(clip_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        remaining = [c for c in track.clips if c.id != clip_id]
        if close_gaps and track.kind == TrackKind.VIDEO:
            remaining = _pack_track_clips(remaining)
        tracks = [
            t.model_copy(update={"clips": remaining}) if t.id == track.id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    def duplicate_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        persist: bool = True,
    ) -> Timeline:
        track, clip = timeline.find_clip(clip_id)
        if track.locked:
            raise ValueError(f"Track {track.name} is locked")
        copy = clip.model_copy(
            update={
                "id": _new_id("clip"),
                "start_seconds": clip.end_seconds,
                "label": f"{clip.label} copy" if clip.label else "Copy",
            }
        )
        new_clips = list(track.clips)
        idx = next(i for i, c in enumerate(track.clips) if c.id == clip_id)
        new_clips.insert(idx + 1, copy)
        tracks = [
            t.model_copy(update={"clips": new_clips}) if t.id == track.id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()

    def set_transition(
        self,
        timeline: Timeline,
        clip_id: str,
        *,
        transition_in: TransitionType | None = None,
        transition_out: TransitionType | None = None,
        transition_duration: float | None = None,
        persist: bool = True,
    ) -> Timeline:
        _, clip = timeline.find_clip(clip_id)
        updates: dict[str, Any] = {}
        if transition_in is not None:
            updates["transition_in"] = transition_in
        if transition_out is not None:
            updates["transition_out"] = transition_out
        if transition_duration is not None:
            updates["transition_duration"] = max(0.0, transition_duration)
        return self._replace_clip(
            timeline, clip_id, clip.model_copy(update=updates), persist=persist
        )

    def seek(self, timeline: Timeline, seconds: float, *, persist: bool = True) -> Timeline:
        board = timeline.model_copy(
            update={"playhead_seconds": max(0.0, seconds)}
        )
        return self.save(board) if persist else board

    def enqueue_export(
        self,
        timeline: Timeline,
        *,
        format: ExportFormat = ExportFormat.MP4,
        aspect: ExportAspect = ExportAspect.LANDSCAPE,
        persist: bool = True,
    ) -> Timeline:
        job = ExportJob(
            format=format,
            aspect=aspect,
            status=ExportJobStatus.QUEUED,
            message=f"Queued {format.value} ({aspect.value}) — references timeline assets only",
        )
        queue = list(timeline.export_queue) + [job]
        board = timeline.model_copy(update={"export_queue": queue})
        return self.save(board) if persist else board.touch()

    def update_export_status(
        self,
        timeline: Timeline,
        job_id: str,
        status: ExportJobStatus,
        *,
        message: str | None = None,
        persist: bool = True,
    ) -> Timeline:
        from src.timeline.models import _utc_iso

        queue = []
        found = False
        for job in timeline.export_queue:
            if job.id == job_id:
                found = True
                queue.append(
                    job.model_copy(
                        update={
                            "status": status,
                            "message": message or job.message,
                            "updated_at": _utc_iso(),
                        }
                    )
                )
            else:
                queue.append(job)
        if not found:
            raise KeyError(f"Export job {job_id!r} not found")
        board = timeline.model_copy(update={"export_queue": queue})
        return self.save(board) if persist else board.touch()

    def preview_at(
        self, timeline: Timeline, seconds: float | None = None
    ) -> dict[str, Any]:
        """Resolve which video clip is under the playhead (no media generation)."""
        t = timeline.playhead_seconds if seconds is None else seconds
        video = timeline.track_by_kind(TrackKind.VIDEO)
        active = None
        if video:
            for clip in video.clips:
                if clip.start_seconds <= t < clip.end_seconds:
                    active = clip
                    break
        return {
            "playhead_seconds": t,
            "duration_seconds": timeline.duration_seconds,
            "clip": active.to_dict() if active else None,
            "media_url": active.media_url if active else None,
            "poster_url": active.poster_url if active else None,
            "scene_id": active.scene_id if active else None,
            "local_time": (
                (t - active.start_seconds + active.in_point) if active else None
            ),
        }

    def _replace_clip(
        self,
        timeline: Timeline,
        clip_id: str,
        new_clip: TimelineClip,
        *,
        persist: bool,
    ) -> Timeline:
        track, _ = timeline.find_clip(clip_id)
        clips = [new_clip if c.id == clip_id else c for c in track.clips]
        tracks = [
            t.model_copy(update={"clips": clips}) if t.id == track.id else t
            for t in timeline.tracks
        ]
        board = timeline.model_copy(update={"tracks": tracks})
        return self.save(board) if persist else board.touch()
