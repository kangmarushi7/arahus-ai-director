"""Built-in export presets for social platforms + custom."""

from __future__ import annotations

from src.export.models import ExportFormat, ExportPreset, ExportPresetId, ExportSettings


PRESETS: dict[ExportPresetId, ExportPreset] = {
    ExportPresetId.YOUTUBE_SHORTS: ExportPreset(
        id=ExportPresetId.YOUTUBE_SHORTS,
        label="YouTube Shorts",
        aspect="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_duration_seconds=60,
        format=ExportFormat.MP4,
        description="Vertical Shorts up to 60s",
    ),
    ExportPresetId.INSTAGRAM_REELS: ExportPreset(
        id=ExportPresetId.INSTAGRAM_REELS,
        label="Instagram Reels",
        aspect="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_duration_seconds=90,
        format=ExportFormat.MP4,
        description="Vertical Reels up to 90s",
    ),
    ExportPresetId.TIKTOK: ExportPreset(
        id=ExportPresetId.TIKTOK,
        label="TikTok",
        aspect="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_duration_seconds=180,
        format=ExportFormat.MP4,
        description="Vertical TikTok up to 3 minutes",
    ),
    ExportPresetId.YOUTUBE: ExportPreset(
        id=ExportPresetId.YOUTUBE,
        label="YouTube",
        aspect="16:9",
        width=1920,
        height=1080,
        fps=30,
        format=ExportFormat.MP4,
        description="Landscape YouTube 1080p",
    ),
    ExportPresetId.X: ExportPreset(
        id=ExportPresetId.X,
        label="X",
        aspect="1:1",
        width=1080,
        height=1080,
        fps=30,
        max_duration_seconds=140,
        format=ExportFormat.MP4,
        description="Square X / Twitter video",
    ),
    ExportPresetId.CUSTOM: ExportPreset(
        id=ExportPresetId.CUSTOM,
        label="Custom",
        aspect="16:9",
        width=1920,
        height=1080,
        fps=24,
        format=ExportFormat.MP4,
        description="User-defined dimensions and format",
    ),
}


def list_presets() -> list[ExportPreset]:
    return list(PRESETS.values())


def settings_from_preset(
    preset_id: ExportPresetId,
    *,
    format: ExportFormat | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    aspect: str | None = None,
    include_subtitles: bool = True,
    include_audio: bool = True,
    custom_label: str | None = None,
) -> ExportSettings:
    preset = PRESETS[preset_id]
    return ExportSettings(
        preset=preset_id,
        format=format or preset.format,
        aspect=aspect or preset.aspect,
        width=width or preset.width,
        height=height or preset.height,
        fps=fps or preset.fps,
        include_subtitles=include_subtitles,
        include_audio=include_audio,
        custom_label=custom_label,
    )
