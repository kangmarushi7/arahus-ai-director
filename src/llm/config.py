"""YAML configuration loading for the LLM router."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.llm.exceptions import LLMConfigError
from src.llm.pricing import PricingTable
from src.llm.retry import RetryPolicy

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "router.yaml"


@dataclass(frozen=True, slots=True)
class TaskRoute:
    """Provider/model selection for one logical task."""

    task: str
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 4000


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Static provider connection settings (secrets resolved at runtime)."""

    name: str
    type: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 120.0
    default_headers: Mapping[str, str] = field(default_factory=dict)

    def resolve_api_key(self) -> str:
        """Read the API key from the environment."""
        key = os.getenv(self.api_key_env, "").strip()
        if not key:
            # Also support values already loaded via python-dotenv / settings.
            from src.config import get_settings

            if self.api_key_env.upper() == "OPENROUTER_API_KEY":
                key = get_settings().llm.require_api_key()
        if not key:
            raise LLMConfigError(
                f"Missing API key for provider {self.name!r} "
                f"(env {self.api_key_env})"
            )
        return key


@dataclass(frozen=True, slots=True)
class LLMRouterConfig:
    """Fully parsed router configuration."""

    default_provider: str
    providers: Mapping[str, ProviderConfig]
    tasks: Mapping[str, TaskRoute]
    retry: RetryPolicy
    pricing: PricingTable
    source_path: Path | None = None

    def route_for(self, task: str) -> TaskRoute:
        """Return the route for ``task`` or raise."""
        cleaned = task.strip().lower()
        try:
            return self.tasks[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self.tasks))
            raise LLMConfigError(
                f"Unknown LLM task {task!r}. Known tasks: {known}"
            ) from exc


def load_router_config(path: Path | str | None = None) -> LLMRouterConfig:
    """Load and validate router YAML from ``path`` (or the packaged default)."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise LLMConfigError(f"LLM router config not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LLMConfigError(f"Invalid LLM router YAML at {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise LLMConfigError(f"LLM router config root must be a mapping: {config_path}")

    return parse_router_config(raw, source_path=config_path)


def parse_router_config(
    raw: Mapping[str, Any],
    *,
    source_path: Path | None = None,
) -> LLMRouterConfig:
    """Parse an in-memory router config mapping."""
    default_provider = str(raw.get("default_provider") or "openrouter").strip()
    providers_raw = raw.get("providers") or {}
    tasks_raw = raw.get("tasks") or {}
    retry_raw = raw.get("retry") or {}
    pricing_raw = raw.get("pricing") or {}

    if not isinstance(providers_raw, Mapping) or not providers_raw:
        raise LLMConfigError("LLM router config requires a non-empty 'providers' map")
    if not isinstance(tasks_raw, Mapping) or not tasks_raw:
        raise LLMConfigError("LLM router config requires a non-empty 'tasks' map")

    providers: dict[str, ProviderConfig] = {}
    for name, value in providers_raw.items():
        if not isinstance(value, Mapping):
            raise LLMConfigError(f"Provider {name!r} config must be a mapping")
        providers[str(name)] = ProviderConfig(
            name=str(name),
            type=str(value.get("type") or name).strip().lower(),
            base_url=str(value.get("base_url") or "").strip().rstrip("/"),
            api_key_env=str(value.get("api_key_env") or "OPENROUTER_API_KEY").strip(),
            timeout_seconds=float(value.get("timeout_seconds") or 120.0),
            default_headers={
                str(k): str(v)
                for k, v in dict(value.get("default_headers") or {}).items()
            },
        )
        if not providers[str(name)].base_url:
            raise LLMConfigError(f"Provider {name!r} is missing base_url")

    if default_provider not in providers:
        raise LLMConfigError(
            f"default_provider {default_provider!r} is not defined in providers"
        )

    tasks: dict[str, TaskRoute] = {}
    for name, value in tasks_raw.items():
        if not isinstance(value, Mapping):
            raise LLMConfigError(f"Task {name!r} config must be a mapping")
        provider = str(value.get("provider") or default_provider).strip()
        model = str(value.get("model") or "").strip()
        if not model:
            raise LLMConfigError(f"Task {name!r} is missing model")
        if provider not in providers:
            raise LLMConfigError(
                f"Task {name!r} references unknown provider {provider!r}"
            )
        tasks[str(name).strip().lower()] = TaskRoute(
            task=str(name).strip().lower(),
            provider=provider,
            model=model,
            temperature=float(value.get("temperature", 0.2)),
            max_tokens=int(value.get("max_tokens") or 4000),
        )

    retry = RetryPolicy(
        max_attempts=int(retry_raw.get("max_attempts") or 3),
        base_delay_seconds=float(retry_raw.get("base_delay_seconds") or 0.5),
        max_delay_seconds=float(retry_raw.get("max_delay_seconds") or 8.0),
        jitter_ratio=float(retry_raw.get("jitter_ratio") or 0.25),
    )
    pricing = PricingTable.from_mapping(
        pricing_raw if isinstance(pricing_raw, Mapping) else None
    )

    return LLMRouterConfig(
        default_provider=default_provider,
        providers=providers,
        tasks=tasks,
        retry=retry,
        pricing=pricing,
        source_path=source_path,
    )
