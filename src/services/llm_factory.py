"""Factory for agent LLM clients backed by the task router."""

from __future__ import annotations

from src.config import get_settings
from src.llm import LLM, get_llm
from src.services.llm import LLMClient

# Map env model slots → router task names.
_MODEL_TASK_HINTS: dict[str, str] = {
    "research_model": "research",
    "director_model": "director",
    "prompt_model": "prompt",
    "review_model": "review",
    "domain_model": "domain",
}


def create_llm(
    model_name: str,
    *,
    task: str | None = None,
    llm: LLM | None = None,
) -> LLMClient:
    """Build an :class:`LLMClient` with an explicit model override.

    Prefer :func:`create_task_llm` for normal agent wiring so ``router.yaml``
    remains the default and env overrides apply cleanly.
    """
    if not model_name.strip():
        raise ValueError("model_name must be a non-empty string")

    settings = get_settings().llm
    resolved_task = (task or _infer_task(model_name.strip(), settings)).strip().lower()
    return LLMClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        model=model_name.strip(),
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        task=resolved_task,
        llm=llm or get_llm(),
    )


def create_task_llm(task: str, *, llm: LLM | None = None) -> LLMClient:
    """Build a client for ``task`` with admin→env→YAML model precedence.

    Precedence:
        1. Admin panel override (``artifacts/admin/model_overrides.json``)
        2. Non-empty env override for the task (``RESEARCH_MODEL``, …)
        3. ``router.yaml`` task route model (empty ``LLMClient.model``)
    """
    if not task.strip():
        raise ValueError("task must be a non-empty string")
    from src.llm.model_overrides import get_admin_model_override

    settings = get_settings().llm
    resolved = task.strip().lower()
    override = get_admin_model_override(resolved) or settings.model_override_for(resolved)
    return LLMClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        model=override or "",
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        task=resolved,
        llm=llm or get_llm(),
    )


def _infer_task(model_name: str, settings: object) -> str:
    for attr, task_name in _MODEL_TASK_HINTS.items():
        configured = getattr(settings, attr, "")
        if isinstance(configured, str) and configured.strip() == model_name:
            return task_name
    return "general"
