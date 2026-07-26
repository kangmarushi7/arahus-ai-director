"""Factory for OpenAI-compatible LLM clients configured via environment."""

from __future__ import annotations

from src.config import get_settings
from src.services.llm import LLMClient


def create_llm(model_name: str) -> LLMClient:
    """Build an :class:`LLMClient` for ``model_name`` using shared config.

    Reads the API key, base URL, temperature, and max tokens from
    :mod:`src.config`. Agents never see provider details — they only receive
    the returned client.

    Args:
        model_name: OpenAI-compatible model id, e.g. ``openai/gpt-oss-20b:free``.

    Returns:
        A configured LLM client ready for :meth:`LLMClient.generate_json`.

    Raises:
        ValueError: If ``model_name`` is empty.
        RuntimeError: If ``OPENROUTER_API_KEY`` is not set.
    """
    if not model_name.strip():
        raise ValueError("model_name must be a non-empty string")

    llm = get_settings().llm
    return LLMClient(
        api_key=llm.require_api_key(),
        base_url=llm.base_url,
        model=model_name.strip(),
        temperature=llm.temperature,
        max_tokens=llm.max_tokens,
    )
