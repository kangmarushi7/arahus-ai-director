"""Tests for admin model overrides and OpenRouter catalog helpers."""

from __future__ import annotations

from pathlib import Path

from src.llm import model_overrides as overrides
from src.llm.openrouter_models import OpenRouterModel
from src.services.llm_factory import create_task_llm
from src.webapp.model_admin import apply_task_model_updates, task_models_payload


def test_model_overrides_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(overrides, "_DEFAULT_PATH", tmp_path / "overrides.json")
    assert overrides.load_overrides() == {}
    saved = overrides.update_overrides(
        {"research": "openai/gpt-4o-mini", "director": "anthropic/claude-sonnet-4"}
    )
    assert saved["research"] == "openai/gpt-4o-mini"
    assert overrides.get_admin_model_override("research") == "openai/gpt-4o-mini"
    overrides.update_overrides({"research": ""})
    assert "research" not in overrides.load_overrides()
    assert overrides.get_admin_model_override("director") == "anthropic/claude-sonnet-4"


def test_create_task_llm_prefers_admin_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(overrides, "_DEFAULT_PATH", tmp_path / "overrides.json")
    overrides.save_overrides({"prompt": "openai/gpt-4o"})
    client = create_task_llm("prompt")
    assert client.model == "openai/gpt-4o"


def test_openrouter_model_estimate() -> None:
    model = OpenRouterModel(
        id="x/test",
        name="Test",
        context_length=8192,
        input_per_million=1.0,
        output_per_million=2.0,
        is_free=False,
    )
    # 1M in + 1M out => $3
    assert model.estimate(input_tokens=1_000_000, output_tokens=1_000_000) == 3.0


def test_task_models_payload_includes_pricing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(overrides, "_DEFAULT_PATH", tmp_path / "overrides.json")
    from src.webapp import model_admin as model_admin_api

    monkeypatch.setattr(
        model_admin_api,
        "get_openrouter_model",
        lambda model_id: OpenRouterModel(
            id=model_id,
            name=model_id,
            context_length=8192,
            input_per_million=0.0,
            output_per_million=0.0,
            is_free=True,
        ),
    )
    payload = task_models_payload()
    assert payload["tasks"]
    research = next(row for row in payload["tasks"] if row["task"] == "research")
    assert "effective_model" in research
    assert research["pricing"]["found"] is True


def test_apply_task_model_updates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(overrides, "_DEFAULT_PATH", tmp_path / "overrides.json")
    from src.webapp import model_admin as model_admin_api

    monkeypatch.setattr(model_admin_api, "get_openrouter_model", lambda model_id: None)
    payload = apply_task_model_updates({"review": "vendor/custom-model"})
    review = next(row for row in payload["tasks"] if row["task"] == "review")
    assert review["effective_model"] == "vendor/custom-model"
    assert review["source"] == "admin"
