"""Subtitle helpers — auto cues + SRT/VTT export."""

from __future__ import annotations

from src.audio.models import NarrationClip, SubtitleCue, SubtitleFormat


def cues_from_narrations(
    narrations: list[NarrationClip],
    *,
    language: str | None = None,
) -> list[SubtitleCue]:
    """Build editable subtitle cues aligned to narration timing."""
    cues: list[SubtitleCue] = []
    for clip in narrations:
        if not clip.text.strip():
            continue
        lang = language or clip.language
        end = clip.start_seconds + max(clip.duration_seconds, 1.0)
        cues.append(
            SubtitleCue(
                scene_id=clip.scene_id,
                start_seconds=clip.start_seconds,
                end_seconds=end,
                text=clip.text.strip(),
                language=lang,
            )
        )
    return cues


def export_subtitles(
    cues: list[SubtitleCue],
    *,
    fmt: SubtitleFormat = SubtitleFormat.SRT,
    language: str | None = None,
) -> str:
    filtered = [
        cue
        for cue in sorted(cues, key=lambda c: c.start_seconds)
        if language is None or cue.language == language
    ]
    if fmt == SubtitleFormat.VTT:
        return _to_vtt(filtered)
    return _to_srt(filtered)


def _ts(seconds: float, *, vtt: bool = False) -> str:
    ms = int(round(seconds * 1000))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    sep = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def _to_srt(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_ts(cue.start_seconds)} --> {_ts(cue.end_seconds)}\n"
            f"{cue.text}\n"
        )
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def _to_vtt(cues: list[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(
            f"{_ts(cue.start_seconds, vtt=True)} --> {_ts(cue.end_seconds, vtt=True)}"
        )
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)
