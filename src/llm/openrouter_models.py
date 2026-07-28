"""Fetch and cache OpenRouter model catalog with pricing."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests

from src.config import get_settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_lock = threading.RLock()
_cache: tuple[float, list["OpenRouterModel"]] | None = None


@dataclass(frozen=True, slots=True)
class OpenRouterModel:
    """One OpenRouter model with normalized USD-per-million pricing."""

    id: str
    name: str
    context_length: int | None
    input_per_million: float
    output_per_million: float
    is_free: bool
    modality: str = ""
    description: str = ""

    def estimate(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimated USD for the given token counts."""
        inp = max(0, int(input_tokens)) / 1_000_000.0 * self.input_per_million
        out = max(0, int(output_tokens)) / 1_000_000.0 * self.output_per_million
        return round(inp + out, 8)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Sample estimate: 2k prompt + 1k completion (admin UI default).
        payload["est_cost_2k_1k"] = self.estimate(input_tokens=2000, output_tokens=1000)
        return payload


def list_openrouter_models(
    *,
    force_refresh: bool = False,
    query: str | None = None,
    include_non_text: bool = False,
) -> list[OpenRouterModel]:
    """Return OpenRouter models (cached), optionally filtered by ``query``."""
    models = _load_models(force_refresh=force_refresh)
    cleaned_query = (query or "").strip().lower()
    result: list[OpenRouterModel] = []
    for model in models:
        if not include_non_text and model.modality and "text" not in model.modality:
            continue
        if cleaned_query:
            hay = f"{model.id} {model.name} {model.description}".lower()
            if cleaned_query not in hay:
                continue
        result.append(model)
    return result


def get_openrouter_model(model_id: str) -> OpenRouterModel | None:
    """Lookup one model by id from the cached catalog."""
    cleaned = model_id.strip()
    if not cleaned:
        return None
    for model in _load_models():
        if model.id == cleaned:
            return model
    return None


def clear_openrouter_models_cache() -> None:
    """Drop the in-memory catalog cache (tests / forced refresh)."""
    global _cache
    with _lock:
        _cache = None


def _load_models(*, force_refresh: bool = False) -> list[OpenRouterModel]:
    global _cache
    now = time.monotonic()
    with _lock:
        if (
            not force_refresh
            and _cache is not None
            and (now - _cache[0]) < _CACHE_TTL_SECONDS
        ):
            return list(_cache[1])

    models = _fetch_models()
    with _lock:
        _cache = (time.monotonic(), models)
    return list(models)


def _fetch_models() -> list[OpenRouterModel]:
    settings = get_settings().llm
    api_key = settings.api_key.get_secret_value().strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to list models")

    url = f"{settings.base_url.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://arahus.ai",
        "X-Title": "Arahus AI Director",
    }
    logger.info("event=openrouter_models_fetch url=%s", url)
    response = requests.get(url, headers=headers, timeout=45)
    if response.status_code >= 400:
        raise RuntimeError(
            f"OpenRouter models fetch failed ({response.status_code}): "
            f"{response.text[:300]}"
        )
    payload = response.json()
    raw_items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        raise RuntimeError("OpenRouter models response missing data[]")

    models: list[OpenRouterModel] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        input_per_token = _as_float(pricing.get("prompt"))
        output_per_token = _as_float(pricing.get("completion"))
        input_per_million = round(input_per_token * 1_000_000.0, 6)
        output_per_million = round(output_per_token * 1_000_000.0, 6)
        architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        modality = str(
            architecture.get("modality")
            or item.get("modality")
            or ""
        ).strip()
        context = item.get("context_length")
        try:
            context_length = int(context) if context is not None else None
        except (TypeError, ValueError):
            context_length = None
        is_free = (
            model_id.endswith(":free")
            or (input_per_million == 0.0 and output_per_million == 0.0)
        )
        models.append(
            OpenRouterModel(
                id=model_id,
                name=str(item.get("name") or model_id).strip(),
                context_length=context_length,
                input_per_million=input_per_million,
                output_per_million=output_per_million,
                is_free=is_free,
                modality=modality,
                description=str(item.get("description") or "")[:400],
            )
        )

    models.sort(key=lambda m: (not m.is_free, m.id.lower()))
    logger.info("event=openrouter_models_loaded count=%s", len(models))
    return models


def _as_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
