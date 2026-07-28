"""Stub export engine — writes placeholder outputs without ffmpeg/vendors."""

from __future__ import annotations

from pathlib import Path

from src.export.models import ExportFormat, RenderJob


def render_stub_output(job: RenderJob, job_dir: Path) -> Path:
    """Produce a deterministic placeholder file for the requested format.

    Architecture only: does not invoke ffmpeg or cloud encoders.
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    settings = job.settings
    fmt = settings.format

    if fmt == ExportFormat.IMAGE_SEQUENCE:
        seq_dir = job_dir / "sequence"
        seq_dir.mkdir(parents=True, exist_ok=True)
        frames = min(24, max(3, settings.fps))
        for index in range(frames):
            frame = seq_dir / f"frame_{index:05d}.txt"
            frame.write_text(
                f"ARAHUS_FRAME project={job.project_id} job={job.id} "
                f"index={index} {settings.width}x{settings.height}@{settings.fps}\n",
                encoding="utf-8",
            )
        marker = job_dir / "sequence.ok"
        marker.write_text(f"{frames} frames\n", encoding="utf-8")
        return seq_dir

    ext = {
        ExportFormat.MP4: "mp4",
        ExportFormat.MOV: "mov",
        ExportFormat.GIF: "gif",
    }[fmt]
    out = job_dir / f"output.{ext}"
    out.write_text(
        "ARAHUS_EXPORT_STUB\n"
        f"project_id={job.project_id}\n"
        f"job_id={job.id}\n"
        f"format={fmt.value}\n"
        f"preset={settings.preset.value}\n"
        f"aspect={settings.aspect}\n"
        f"resolution={settings.width}x{settings.height}\n"
        f"fps={settings.fps}\n"
        "encoder=stub\n"
        "note=Replace with real encoder worker later\n",
        encoding="utf-8",
    )
    return out
