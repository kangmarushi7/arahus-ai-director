"""YAML configuration for the video router and model registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.media.request import GenerationProfileName, QualityMode
from src.video.exceptions import VideoConfigError

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "video_router.yaml"
DEFAULT_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

_VALID_QUALITIES = frozenset({"preview", "production", "experimental"})
_VALID_PROFILES = frozenset({"preview", "production", "cinematic"})


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Static provider connection settings."""

    name: str
    type: str
    api_key_env: str = "RUNPOD_API_KEY"
    endpoint_id_env: str = "RUNPOD_VIDEO_ENDPOINT_ID"
    base_url: str = "https://api.runpod.ai/v2"
    timeout_seconds: float = 300.0
    enabled: bool = False
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One registered video model (YAML-driven)."""

    key: str
    provider: str
    model_id: str
    quality_modes: tuple[QualityMode, ...]
    duration: float = 5.0
    fps: int = 24
    width: int = 720
    height: int = 1280
    aspect_ratio: str = "9:16"
    motion: str = ""
    cost_per_second: float = 0.0
    description: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """A generation profile that overrides model defaults."""

    name: GenerationProfileName
    duration: float | None = None
    fps: int | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    motion: str | None = None
    quality_label: str | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QualityRoute:
    """Map a quality mode → model key + default profile."""

    quality: QualityMode
    model: str
    profile: GenerationProfileName


@dataclass(frozen=True, slots=True)
class VideoRouterConfig:
    """Fully parsed video router configuration."""

    default_provider: str
    default_quality: QualityMode
    default_profile: GenerationProfileName
    providers: Mapping[str, ProviderConfig]
    models: Mapping[str, ModelSpec]
    profiles: Mapping[str, ProfileSpec]
    quality_routes: Mapping[str, QualityRoute]
    source_path: Path | None = None

    def model_for(self, key: str) -> ModelSpec:
        cleaned = key.strip().lower()
        try:
            return self.models[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.models))
            raise VideoConfigError(
                f"Unknown video model {key!r}. Known models: {known}"
            ) from exc

    def profile_for(self, name: str) -> ProfileSpec:
        cleaned = name.strip().lower()
        try:
            return self.profiles[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.profiles))
            raise VideoConfigError(
                f"Unknown generation profile {name!r}. Known profiles: {known}"
            ) from exc

    def quality_route(self, quality: str) -> QualityRoute:
        cleaned = quality.strip().lower()
        try:
            return self.quality_routes[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.quality_routes))
            raise VideoConfigError(
                f"Unknown quality mode {quality!r}. Known modes: {known}"
            ) from exc


def load_video_config(path: Path | str | None = None) -> VideoRouterConfig:
    """Load and validate video router YAML from ``path`` (or packaged default)."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise VideoConfigError(f"Video router config not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise VideoConfigError(
            f"Invalid video router YAML at {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise VideoConfigError(
            f"Video router config root must be a mapping: {config_path}"
        )

    profiles_dir = config_path.parent.parent / "profiles"
    if not profiles_dir.is_dir():
        profiles_dir = DEFAULT_PROFILES_DIR
    return parse_video_config(
        raw,
        source_path=config_path,
        profiles_dir=profiles_dir,
    )


def load_profile_files(profiles_dir: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Load ``preview.yaml`` / ``production.yaml`` / ``cinematic.yaml`` maps."""
    root = Path(profiles_dir) if profiles_dir else DEFAULT_PROFILES_DIR
    loaded: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return loaded
    for name in sorted(_VALID_PROFILES):
        path = root / f"{name}.yaml"
        if not path.is_file():
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise VideoConfigError(f"Invalid profile YAML at {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise VideoConfigError(f"Profile {name!r} root must be a mapping: {path}")
        loaded[name] = dict(payload)
    return loaded


def parse_video_config(
    raw: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    profiles_dir: Path | str | None = None,
) -> VideoRouterConfig:
    """Parse an in-memory video router config mapping."""
    default_provider = str(raw.get("default_provider") or "runpod").strip()
    default_quality = _require_quality(raw.get("default_quality") or "production")
    default_profile = _require_profile(raw.get("default_profile") or "production")

    providers_raw = raw.get("providers") or {}
    models_raw = raw.get("models") or {}
    profiles_raw = dict(raw.get("profiles") or {})
    quality_raw = raw.get("quality_modes") or {}

    # File-backed profiles first; inline YAML overrides win.
    file_profiles = load_profile_files(profiles_dir)
    merged_profiles: dict[str, Any] = {**file_profiles, **profiles_raw}

    if not isinstance(providers_raw, Mapping) or not providers_raw:
        raise VideoConfigError("Video router config requires a non-empty 'providers' map")
    if not isinstance(models_raw, Mapping) or not models_raw:
        raise VideoConfigError("Video router config requires a non-empty 'models' map")
    if not merged_profiles:
        raise VideoConfigError(
            "Video router config requires profiles (YAML files or inline map)"
        )
    if not isinstance(quality_raw, Mapping) or not quality_raw:
        raise VideoConfigError(
            "Video router config requires a non-empty 'quality_modes' map"
        )

    providers: dict[str, ProviderConfig] = {}
    for name, value in providers_raw.items():
        if not isinstance(value, Mapping):
            raise VideoConfigError(f"Provider {name!r} config must be a mapping")
        providers[str(name)] = ProviderConfig(
            name=str(name),
            type=str(value.get("type") or name).strip().lower(),
            api_key_env=str(value.get("api_key_env") or "RUNPOD_API_KEY"),
            endpoint_id_env=str(
                value.get("endpoint_id_env") or "RUNPOD_VIDEO_ENDPOINT_ID"
            ),
            base_url=str(value.get("base_url") or "https://api.runpod.ai/v2").rstrip(
                "/"
            ),
            timeout_seconds=float(value.get("timeout_seconds") or 300.0),
            enabled=bool(value.get("enabled", False)),
            extras={
                key: val
                for key, val in value.items()
                if key
                not in {
                    "type",
                    "api_key_env",
                    "endpoint_id_env",
                    "base_url",
                    "timeout_seconds",
                    "enabled",
                }
            },
        )

    models: dict[str, ModelSpec] = {}
    for key, value in models_raw.items():
        if not isinstance(value, Mapping):
            raise VideoConfigError(f"Model {key!r} config must be a mapping")
        modes_raw = value.get("quality_modes") or ["production"]
        if not isinstance(modes_raw, list) or not modes_raw:
            raise VideoConfigError(f"Model {key!r} requires quality_modes list")
        modes = tuple(_require_quality(item) for item in modes_raw)
        provider = str(value.get("provider") or default_provider).strip()
        if provider not in providers:
            raise VideoConfigError(
                f"Model {key!r} references unknown provider {provider!r}"
            )
        models[str(key).strip().lower()] = ModelSpec(
            key=str(key).strip().lower(),
            provider=provider,
            model_id=str(value.get("model_id") or key).strip(),
            quality_modes=modes,
            duration=float(value.get("duration") or 5.0),
            fps=int(value.get("fps") or 24),
            width=int(value.get("width") or 720),
            height=int(value.get("height") or 1280),
            aspect_ratio=str(value.get("aspect_ratio") or "9:16"),
            motion=str(value.get("motion") or ""),
            cost_per_second=float(value.get("cost_per_second") or 0.0),
            description=str(value.get("description") or ""),
            extras={
                k: v
                for k, v in value.items()
                if k
                not in {
                    "provider",
                    "model_id",
                    "quality_modes",
                    "duration",
                    "fps",
                    "width",
                    "height",
                    "aspect_ratio",
                    "motion",
                    "cost_per_second",
                    "description",
                }
            },
        )

    profiles: dict[str, ProfileSpec] = {}
    for name, value in merged_profiles.items():
        if not isinstance(value, Mapping):
            raise VideoConfigError(f"Profile {name!r} config must be a mapping")
        profile_name = _require_profile(name)
        reserved = {
            "duration",
            "fps",
            "width",
            "height",
            "aspect_ratio",
            "motion",
            "quality",
        }
        profiles[profile_name] = ProfileSpec(
            name=profile_name,
            duration=(
                float(value["duration"]) if value.get("duration") is not None else None
            ),
            fps=int(value["fps"]) if value.get("fps") is not None else None,
            width=int(value["width"]) if value.get("width") is not None else None,
            height=int(value["height"]) if value.get("height") is not None else None,
            aspect_ratio=(
                str(value["aspect_ratio"])
                if value.get("aspect_ratio") is not None
                else None
            ),
            motion=str(value["motion"]) if value.get("motion") is not None else None,
            quality_label=(
                str(value["quality"]) if value.get("quality") is not None else None
            ),
            extras={k: v for k, v in value.items() if k not in reserved},
        )

    quality_routes: dict[str, QualityRoute] = {}
    for name, value in quality_raw.items():
        if not isinstance(value, Mapping):
            raise VideoConfigError(f"Quality mode {name!r} config must be a mapping")
        quality = _require_quality(name)
        model_key = str(value.get("model") or "").strip().lower()
        if not model_key or model_key not in models:
            raise VideoConfigError(
                f"Quality mode {quality!r} references unknown model {model_key!r}"
            )
        profile_name = _require_profile(value.get("profile") or default_profile)
        if profile_name not in profiles:
            raise VideoConfigError(
                f"Quality mode {quality!r} references unknown profile {profile_name!r}"
            )
        if quality not in models[model_key].quality_modes:
            raise VideoConfigError(
                f"Model {model_key!r} does not support quality mode {quality!r}"
            )
        quality_routes[quality] = QualityRoute(
            quality=quality,
            model=model_key,
            profile=profile_name,
        )

    if default_quality not in quality_routes:
        raise VideoConfigError(
            f"default_quality {default_quality!r} is not defined under quality_modes"
        )
    if default_profile not in profiles:
        raise VideoConfigError(
            f"default_profile {default_profile!r} is not defined under profiles"
        )
    if default_provider not in providers:
        raise VideoConfigError(
            f"default_provider {default_provider!r} is not defined under providers"
        )

    return VideoRouterConfig(
        default_provider=default_provider,
        default_quality=default_quality,
        default_profile=default_profile,
        providers=providers,
        models=models,
        profiles=profiles,
        quality_routes=quality_routes,
        source_path=source_path,
    )


def _require_quality(value: object) -> QualityMode:
    text = str(value).strip().lower()
    if text not in _VALID_QUALITIES:
        raise VideoConfigError(
            f"Invalid quality mode {value!r}; expected one of "
            f"{sorted(_VALID_QUALITIES)}"
        )
    return text  # type: ignore[return-value]


def _require_profile(value: object) -> GenerationProfileName:
    text = str(value).strip().lower()
    if text not in _VALID_PROFILES:
        raise VideoConfigError(
            f"Invalid generation profile {value!r}; expected one of "
            f"{sorted(_VALID_PROFILES)}"
        )
    return text  # type: ignore[return-value]
