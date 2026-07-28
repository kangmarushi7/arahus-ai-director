"""Admin API helpers for model selection and cost estimates."""

from __future__ import annotations

from typing import Any

from src.llm.model_overrides import TASKS, effective_task_routes, update_overrides
from src.llm.openrouter_models import (
    get_openrouter_model,
    list_openrouter_models,
)


def models_catalog_payload(
    *,
    query: str | None = None,
    force_refresh: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    """Serialize OpenRouter catalog for the admin UI."""
    models = list_openrouter_models(force_refresh=force_refresh, query=query)
    capped = models[: max(1, min(limit, 2000))]
    return {
        "count": len(capped),
        "total_matched": len(models),
        "models": [model.to_dict() for model in capped],
    }


def task_models_payload() -> dict[str, Any]:
    """Current per-task routes + pricing for the selected models."""
    rows = effective_task_routes()
    enriched: list[dict[str, Any]] = []
    for row in rows:
        model_id = str(row["effective_model"])
        catalog = get_openrouter_model(model_id)
        estimate_input = 2000
        estimate_output = min(1000, int(row.get("max_tokens") or 1000))
        if catalog is None:
            pricing = {
                "found": False,
                "input_per_million": None,
                "output_per_million": None,
                "is_free": model_id.endswith(":free"),
                "est_cost_sample": None,
                "sample_input_tokens": estimate_input,
                "sample_output_tokens": estimate_output,
            }
        else:
            pricing = {
                "found": True,
                "name": catalog.name,
                "input_per_million": catalog.input_per_million,
                "output_per_million": catalog.output_per_million,
                "is_free": catalog.is_free,
                "context_length": catalog.context_length,
                "est_cost_sample": catalog.estimate(
                    input_tokens=estimate_input,
                    output_tokens=estimate_output,
                ),
                "sample_input_tokens": estimate_input,
                "sample_output_tokens": estimate_output,
            }
        enriched.append({**row, "pricing": pricing})
    return {"tasks": enriched, "task_names": list(TASKS)}


def apply_task_model_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Apply admin model selections and return the refreshed payload."""
    if not isinstance(updates, dict):
        raise ValueError("updates must be an object of task→model")
    partial: dict[str, str | None] = {}
    for task, model in updates.items():
        key = str(task).strip().lower()
        if key not in TASKS:
            raise ValueError(f"Unknown task {task!r}. Known: {', '.join(TASKS)}")
        if model is None:
            partial[key] = None
        else:
            partial[key] = str(model).strip()
    update_overrides(partial)
    return task_models_payload()
