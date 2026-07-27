"""Provider-agnostic LLM router for Arahus.

Public surface::

    from src.llm import get_llm

    response = get_llm().generate(task="research", messages=[...])
"""

from __future__ import annotations

from src.llm.client import LLM, get_llm, reset_llm_singleton
from src.llm.config import LLMRouterConfig, load_router_config, parse_router_config
from src.llm.exceptions import (
    LLMConfigError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRoutingError,
    LLMTimeoutError,
)
from src.llm.metrics import LLMMetrics
from src.llm.models import ChatMessage, LLMResponse, ProviderCompletion
from src.llm.pricing import ModelPrice, PricingTable
from src.llm.providers import LLMProvider, OpenRouterProvider
from src.llm.retry import RetryPolicy, RetryState, call_with_retry, is_retriable
from src.llm.router import LLMRouter

__all__ = [
    "ChatMessage",
    "LLM",
    "LLMConfigError",
    "LLMError",
    "LLMMetrics",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMRouter",
    "LLMRouterConfig",
    "LLMRoutingError",
    "LLMTimeoutError",
    "ModelPrice",
    "OpenRouterProvider",
    "PricingTable",
    "ProviderCompletion",
    "RetryPolicy",
    "RetryState",
    "call_with_retry",
    "get_llm",
    "is_retriable",
    "load_router_config",
    "parse_router_config",
    "reset_llm_singleton",
]
