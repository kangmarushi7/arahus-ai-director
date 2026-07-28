"""Load / parse audio router YAML (provider registry)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from src.audio.exceptions import AudioConfigError
from src.models.base import StrictModel

_DEFAULT_YAML = Path(__file__).resolve().parent / "configs" / "audio_router.yaml"


class ProviderConfig(StrictModel):
    type: str
    enabled: bool = True
    api_key_env: str | None = None
    endpoint_id_env: str | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=120.0, ge=1.0)
    extras: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(StrictModel):
    provider: str
    model_id: str
    description: str = ""
    modes: list[str] = Field(default_factory=lambda: ["tts"])
    sample_rate: int = Field(default=24000, ge=8000)
    format: str = "wav"
    cost_per_second: float = Field(default=0.0, ge=0.0)


class QualityModeConfig(StrictModel):
    model: str


class AudioRouterConfig(StrictModel):
    default_provider: str = "stub"
    default_quality: str = "production"
    default_profile: str = "production"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    quality_modes: dict[str, QualityModeConfig] = Field(default_factory=dict)


def load_audio_config(path: str | Path | None = None) -> AudioRouterConfig:
    target = Path(path) if path else _DEFAULT_YAML
    if not target.is_file():
        raise AudioConfigError(f"Audio router config not found: {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise AudioConfigError(f"Failed to parse {target}: {exc}") from exc
    try:
        return AudioRouterConfig.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise AudioConfigError(f"Invalid audio router config: {exc}") from exc
