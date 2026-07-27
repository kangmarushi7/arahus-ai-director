"""Shared progress reporting for pipeline stages and the studio UI."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

PIPELINE_STAGES: tuple[str, ...] = (
    "Domain",
    "Research",
    "Director",
    "Prompt",
    "Review",
    "Images",
)

STAGE_BAR_WIDTH = 10


@dataclass(frozen=True)
class ProgressUpdate:
    """One live-progress event for consoles and dashboards."""

    message: str
    fraction: float
    stage_panel: str
    stages: Mapping[str, float]


# Preferred sink: receives a structured :class:`ProgressUpdate`.
ProgressCallback = Callable[[ProgressUpdate], None]


@dataclass
class ProgressReporter:
    """Tracks overall fraction, per-stage bars, ETA, and forwards step logs."""

    callback: ProgressCallback | None = None
    fraction: float = 0.0
    started_at: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(
        default_factory=lambda: {name: 0.0 for name in PIPELINE_STAGES}
    )
    active_stage: str | None = None
    _last_eta_seconds: float | None = None

    def begin_stage(self, name: str) -> None:
        """Mark ``name`` as the active stage and start its bar at a low fill."""
        self._require_stage(name)
        if self.active_stage and self.stages.get(self.active_stage, 0.0) < 1.0:
            # Leaving a stage mid-flight still counts it as finished for the UI.
            self.stages[self.active_stage] = 1.0
        self.active_stage = name
        self.stages[name] = max(self.stages.get(name, 0.0), 0.08)

    def set_stage(self, name: str, fraction: float) -> None:
        """Set absolute progress for a named stage (``0.0``–``1.0``)."""
        self._require_stage(name)
        self.stages[name] = max(0.0, min(1.0, float(fraction)))
        self.active_stage = name

    def complete_stage(self, name: str) -> None:
        """Fill a stage bar to completion."""
        self._require_stage(name)
        self.stages[name] = 1.0
        if self.active_stage == name:
            self.active_stage = None

    def emit(self, message: str, *, progress: float | None = None) -> None:
        """Log ``message`` and optionally advance the overall fraction."""
        if progress is not None:
            self.fraction = max(self.fraction, min(1.0, float(progress)))
        if self.callback is not None:
            self.callback(
                ProgressUpdate(
                    message=message,
                    fraction=self.fraction,
                    stage_panel=self.format_stage_panel(),
                    stages=dict(self.stages),
                )
            )

    def format_stage_panel(self, *, bar_width: int = STAGE_BAR_WIDTH) -> str:
        """Render the Research/Director/… ASCII progress panel."""
        width = max(1, int(bar_width))
        lines: list[str] = []
        for name in PIPELINE_STAGES:
            frac = max(0.0, min(1.0, float(self.stages.get(name, 0.0))))
            filled = int(round(frac * width))
            if frac > 0 and filled == 0:
                filled = 1
            if frac >= 1.0:
                filled = width
            bar = "█" * filled + "░" * (width - filled)
            lines.append(name)
            lines.append(bar)
        return "\n".join(lines)

    def eta_seconds(self) -> float | None:
        """Estimate remaining seconds from elapsed time and current fraction."""
        if self.fraction < 0.03:
            return None
        elapsed = time.perf_counter() - self.started_at
        remaining = elapsed * (1.0 - self.fraction) / self.fraction
        # Smooth wild swings early in the run.
        if self._last_eta_seconds is not None:
            remaining = 0.65 * self._last_eta_seconds + 0.35 * remaining
        self._last_eta_seconds = max(0.0, remaining)
        return self._last_eta_seconds

    @staticmethod
    def _require_stage(name: str) -> None:
        if name not in PIPELINE_STAGES:
            raise ValueError(
                f"Unknown pipeline stage {name!r}; expected one of {PIPELINE_STAGES}"
            )


def format_duration(seconds: float | None) -> str:
    """Format seconds as a short human-readable duration."""
    if seconds is None:
        return "calculating…"
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
