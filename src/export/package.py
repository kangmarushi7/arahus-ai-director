"""Build a project package folder (storyboard, timeline, media refs, subs, metadata)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.export.models import ProjectPackageManifest, RenderJob


def build_project_package(
    *,
    job: RenderJob,
    dest: Path,
    project: dict[str, Any],
    storyboard: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
    memory: dict[str, Any] | None,
    audio: dict[str, Any] | None,
    subtitles_srt: str | None = None,
    subtitles_vtt: str | None = None,
) -> ProjectPackageManifest:
    """Write a self-contained package directory. Media is referenced, not re-encoded."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    formats: list[str] = ["json"]

    def _write(name: str, payload: Any) -> None:
        path = dest / name
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        files.append(name)

    _write(
        "metadata.json",
        {
            "project_id": job.project_id,
            "render_job_id": job.id,
            "settings": job.settings.model_dump(mode="json"),
            "version": 1,
        },
    )
    _write("project.json", project)
    if storyboard is not None:
        _write("storyboard.json", storyboard)
        prompts = [
            {
                "scene_id": scene.get("id"),
                "title": scene.get("title"),
                "image_prompt": scene.get("image_prompt"),
                "negative_prompt": scene.get("negative_prompt"),
            }
            for scene in storyboard.get("scenes", [])
        ]
        _write("prompts.json", prompts)
    if timeline is not None:
        _write("timeline.json", timeline)
    if memory is not None:
        _write("memory.json", memory)
    if audio is not None:
        _write("audio.json", audio)
    if subtitles_srt:
        _write("subtitles.srt", subtitles_srt)
        formats.append("srt")
    if subtitles_vtt:
        _write("subtitles.vtt", subtitles_vtt)
        formats.append("vtt")

    # Media asset manifest (URLs / paths only — no download required for architecture sprint).
    assets: list[dict[str, Any]] = []
    if storyboard:
        for scene in storyboard.get("scenes", []):
            image = scene.get("image") or {}
            video = scene.get("video") or {}
            if image.get("url"):
                assets.append(
                    {
                        "kind": "image",
                        "scene_id": scene.get("id"),
                        "url": image["url"],
                        "host": urlparse(image["url"]).netloc,
                    }
                )
            if video.get("url"):
                assets.append(
                    {
                        "kind": "video",
                        "scene_id": scene.get("id"),
                        "url": video["url"],
                        "host": urlparse(video["url"]).netloc,
                    }
                )
    if audio:
        for narr in audio.get("narrations", []):
            if narr.get("audio_url"):
                assets.append(
                    {
                        "kind": "voice",
                        "scene_id": narr.get("scene_id"),
                        "url": narr["audio_url"],
                    }
                )
        for bed in audio.get("music", []):
            if bed.get("audio_url"):
                assets.append({"kind": "music", "url": bed["audio_url"]})
        for cue in audio.get("sfx", []):
            if cue.get("audio_url"):
                assets.append({"kind": "sfx", "url": cue["audio_url"]})
    _write("media_assets.json", {"assets": assets, "count": len(assets)})

    manifest = ProjectPackageManifest(
        project_id=job.project_id,
        render_job_id=job.id,
        files=files,
        formats=formats,
        metadata={
            "preset": job.settings.preset.value,
            "format": job.settings.format.value,
            "aspect": job.settings.aspect,
            "asset_count": len(assets),
        },
    )
    _write("package_manifest.json", manifest.model_dump(mode="json"))
    return manifest
