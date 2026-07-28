"""Runtime admin overrides for per-task LLM models."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.llm.config import load_router_config

_DEFAULT_PATH = Path("artifacts") / "admin" / "model_overrides.json"
_lock = threading.RLock()

TASKS = ("domain", "research", "director", "prompt", "review", "general")


def overrides_path() -> Path:
    """Return the JSON file used for admin model overrides."""
    path = _DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_overrides() -> dict[str, str]:
    """Load task→model overrides (empty strings omitted)."""
    path = overrides_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for task, model in raw.items():
        key = str(task).strip().lower()
        value = str(model or "").strip()
        if key in TASKS and value:
            cleaned[key] = value
    return cleaned


def save_overrides(overrides: dict[str, str | None]) -> dict[str, str]:
    """Replace admin overrides. Empty/None clears a task override."""
    cleaned: dict[str, str] = {}
    for task in TASKS:
        value = str(overrides.get(task) or "").strip()
        if value:
            cleaned[task] = value
    path = overrides_path()
    with _lock:
        path.write_text(
            json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return cleaned


def update_overrides(partial: dict[str, str | None]) -> dict[str, str]:
    """Merge ``partial`` into existing overrides (None/'' clears a key)."""
    current = load_overrides()
    for task, model in partial.items():
        key = str(task).strip().lower()
        if key not in TASKS:
            continue
        value = str(model or "").strip()
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    return save_overrides(current)


def get_admin_model_override(task: str) -> str | None:
    """Return admin override for ``task``, if any."""
    cleaned = task.strip().lower()
    return load_overrides().get(cleaned) or None


def clear_overrides() -> None:
    """Remove all admin model overrides."""
    save_overrides({})


def effective_task_routes() -> list[dict[str, Any]]:
    """Describe each task route with yaml/env/admin/effective model."""
    from src.config import get_settings

    settings = get_settings().llm
    router = load_router_config()
    admin = load_overrides()
    rows: list[dict[str, Any]] = []
    for task in TASKS:
        route = router.tasks.get(task)
        if route is None:
            continue
        yaml_model = route.model
        env_model = settings.model_override_for(task)
        admin_model = admin.get(task)
        if admin_model:
            effective = admin_model
            source = "admin"
        elif env_model:
            effective = env_model
            source = "env"
        else:
            effective = yaml_model
            source = "yaml"
        rows.append(
            {
                "task": task,
                "provider": route.provider,
                "temperature": route.temperature,
                "max_tokens": route.max_tokens,
                "yaml_model": yaml_model,
                "env_model": env_model,
                "admin_model": admin_model,
                "effective_model": effective,
                "source": source,
            }
        )
    return rows
