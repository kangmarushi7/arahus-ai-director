"""YAML configuration for the image router and model registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.image.exceptions import ImageConfigError
from src.image.models import GenerationProfileName, QualityMode

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "image_router.yaml"

_VALID_QUALITIES = frozenset({"preview", "production", "experimental"})
_VALID_PROFILES = frozenset({"preview", "production", "cinematic"})


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Static provider connection settings."""

    name: str
    type: str
    api_key_env: str = "RUNPOD_API_KEY"
    endpoint_id_env: str = "RUNPOD_ENDPOINT_ID"
    base_url: str = "https://api.runpod.ai/v2"
    timeout_seconds: float = 120.0
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One registered image model (YAML-driven)."""

    key: str
    provider: str
    model_id: str
    quality_modes: tuple[QualityMode, ...]
    width: int = 1024
    height: int = 1024
    steps: int = 28
    guidance_scale: float = 3.5
    cost_per_image: float = 0.0
    description: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """A generation profile that overrides model defaults."""

    name: GenerationProfileName
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    guidance_scale: float | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QualityRoute:
    """Map a quality mode → model key + default profile."""

    quality: QualityMode
    model: str
    profile: GenerationProfileName


@dataclass(frozen=True, slots=True)
class ImageRouterConfig:
    """Fully parsed image router configuration."""

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
            raise ImageConfigError(
                f"Unknown image model {key!r}. Known models: {known}"
            ) from exc

    def profile_for(self, name: str) -> ProfileSpec:
        cleaned = name.strip().lower()
        try:
            return self.profiles[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.profiles))
            raise ImageConfigError(
                f"Unknown generation profile {name!r}. Known profiles: {known}"
            ) from exc

    def quality_route(self, quality: str) -> QualityRoute:
        cleaned = quality.strip().lower()
        try:
            return self.quality_routes[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.quality_routes))
            raise ImageConfigError(
                f"Unknown quality mode {quality!r}. Known modes: {known}"
            ) from exc


def load_image_config(path: Path | str | None = None) -> ImageRouterConfig:
    """Load and validate image router YAML from ``path`` (or packaged default)."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ImageConfigError(f"Image router config not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ImageConfigError(
            f"Invalid image router YAML at {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ImageConfigError(
            f"Image router config root must be a mapping: {config_path}"
        )
    return parse_image_config(raw, source_path=config_path)


def parse_image_config(
    raw: Mapping[str, Any],
    *,
    source_path: Path | None = None,
) -> ImageRouterConfig:
    """Parse an in-memory image router config mapping."""
    default_provider = str(raw.get("default_provider") or "runpod").strip()
    default_quality = _require_quality(raw.get("default_quality") or "production")
    default_profile = _require_profile(raw.get("default_profile") or "production")

    providers_raw = raw.get("providers") or {}
    models_raw = raw.get("models") or {}
    profiles_raw = raw.get("profiles") or {}
    quality_raw = raw.get("quality_modes") or {}

    if not isinstance(providers_raw, Mapping) or not providers_raw:
        raise ImageConfigError("Image router config requires a non-empty 'providers' map")
    if not isinstance(models_raw, Mapping) or not models_raw:
        raise ImageConfigError("Image router config requires a non-empty 'models' map")
    if not isinstance(profiles_raw, Mapping) or not profiles_raw:
        raise ImageConfigError("Image router config requires a non-empty 'profiles' map")
    if not isinstance(quality_raw, Mapping) or not quality_raw:
        raise ImageConfigError(
            "Image router config requires a non-empty 'quality_modes' map"
        )

    providers: dict[str, ProviderConfig] = {}
    for name, value in providers_raw.items():
        if not isinstance(value, Mapping):
            raise ImageConfigError(f"Provider {name!r} config must be a mapping")
        providers[str(name)] = ProviderConfig(
            name=str(name),
            type=str(value.get("type") or name).strip().lower(),
            api_key_env=str(value.get("api_key_env") or "RUNPOD_API_KEY"),
            endpoint_id_env=str(value.get("endpoint_id_env") or "RUNPOD_ENDPOINT_ID"),
            base_url=str(value.get("base_url") or "https://api.runpod.ai/v2").rstrip(
                "/"
            ),
            timeout_seconds=float(value.get("timeout_seconds") or 120.0),
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
                }
            },
        )

    models: dict[str, ModelSpec] = {}
    for key, value in models_raw.items():
        if not isinstance(value, Mapping):
            raise ImageConfigError(f"Model {key!r} config must be a mapping")
        modes_raw = value.get("quality_modes") or ["production"]
        if not isinstance(modes_raw, list) or not modes_raw:
            raise ImageConfigError(f"Model {key!r} requires quality_modes list")
        modes = tuple(_require_quality(item) for item in modes_raw)
        provider = str(value.get("provider") or default_provider).strip()
        if provider not in providers:
            raise ImageConfigError(
                f"Model {key!r} references unknown provider {provider!r}"
            )
        models[str(key).strip().lower()] = ModelSpec(
            key=str(key).strip().lower(),
            provider=provider,
            model_id=str(value.get("model_id") or key).strip(),
            quality_modes=modes,
            width=int(value.get("width") or 1024),
            height=int(value.get("height") or 1024),
            steps=int(value.get("steps") or 28),
            guidance_scale=float(value.get("guidance_scale") or 3.5),
            cost_per_image=float(value.get("cost_per_image") or 0.0),
            description=str(value.get("description") or ""),
            extras={
                k: v
                for k, v in value.items()
                if k
                not in {
                    "provider",
                    "model_id",
                    "quality_modes",
                    "width",
                    "height",
                    "steps",
                    "guidance_scale",
                    "cost_per_image",
                    "description",
                }
            },
        )

    profiles: dict[str, ProfileSpec] = {}
    for name, value in profiles_raw.items():
        if not isinstance(value, Mapping):
            raise ImageConfigError(f"Profile {name!r} config must be a mapping")
        profile_name = _require_profile(name)
        profiles[profile_name] = ProfileSpec(
            name=profile_name,
            width=int(value["width"]) if value.get("width") is not None else None,
            height=int(value["height"]) if value.get("height") is not None else None,
            steps=int(value["steps"]) if value.get("steps") is not None else None,
            guidance_scale=(
                float(value["guidance_scale"])
                if value.get("guidance_scale") is not None
                else None
            ),
            extras={
                k: v
                for k, v in value.items()
                if k not in {"width", "height", "steps", "guidance_scale"}
            },
        )

    quality_routes: dict[str, QualityRoute] = {}
    for name, value in quality_raw.items():
        if not isinstance(value, Mapping):
            raise ImageConfigError(f"Quality mode {name!r} config must be a mapping")
        quality = _require_quality(name)
        model_key = str(value.get("model") or "").strip().lower()
        if not model_key or model_key not in models:
            raise ImageConfigError(
                f"Quality mode {quality!r} references unknown model {model_key!r}"
            )
        profile_name = _require_profile(value.get("profile") or default_profile)
        if profile_name not in profiles:
            raise ImageConfigError(
                f"Quality mode {quality!r} references unknown profile {profile_name!r}"
            )
        if quality not in models[model_key].quality_modes:
            raise ImageConfigError(
                f"Model {model_key!r} does not support quality mode {quality!r}"
            )
        quality_routes[quality] = QualityRoute(
            quality=quality,
            model=model_key,
            profile=profile_name,
        )

    if default_quality not in quality_routes:
        raise ImageConfigError(
            f"default_quality {default_quality!r} is not defined under quality_modes"
        )
    if default_profile not in profiles:
        raise ImageConfigError(
            f"default_profile {default_profile!r} is not defined under profiles"
        )
    if default_provider not in providers:
        raise ImageConfigError(
            f"default_provider {default_provider!r} is not defined under providers"
        )

    return ImageRouterConfig(
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
        raise ImageConfigError(
            f"Invalid quality mode {value!r}; expected one of "
            f"{sorted(_VALID_QUALITIES)}"
        )
    return text  # type: ignore[return-value]


def _require_profile(value: object) -> GenerationProfileName:
    text = str(value).strip().lower()
    if text not in _VALID_PROFILES:
        raise ImageConfigError(
            f"Invalid generation profile {value!r}; expected one of "
            f"{sorted(_VALID_PROFILES)}"
        )
    return text  # type: ignore[return-value]
