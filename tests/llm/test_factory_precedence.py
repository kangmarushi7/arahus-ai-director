"""Tests for LLM factory model precedence (env override vs router.yaml)."""

from __future__ import annotations

from src.config import reload_settings
from src.services.llm_factory import create_task_llm


def test_create_task_llm_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("RESEARCH_MODEL", "openai/env-research")
    reload_settings()
    client = create_task_llm("research")
    assert client.task == "research"
    assert client.model == "openai/env-research"
    reload_settings()


def test_create_task_llm_binds_task_name(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("DIRECTOR_MODEL", "openai/env-director")
    reload_settings()
    client = create_task_llm("director")
    assert client.task == "director"
    assert client.model == "openai/env-director"
    reload_settings()


def test_model_override_for_reads_settings(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PROMPT_MODEL", "openai/env-prompt")
    reload_settings()
    from src.config import get_settings

    assert get_settings().llm.model_override_for("prompt") == "openai/env-prompt"
    reload_settings()
