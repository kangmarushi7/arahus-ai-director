"""Prompt Composition and Optimization Engine for Arahus.

Deterministic, LLM-free assembly and ranking of structured prompts from
reusable components, domain YAML defaults, injectable packs, and style
variants.
"""

from __future__ import annotations

from src.prompt.builder import (
    PromptBuilder,
    apply_contribution,
    dedupe_preserve_order,
    merge_csv_text,
    merge_quality_tags,
    normalize_components,
    normalize_whitespace,
)
from src.prompt.composer import PromptComposer
from src.prompt.models import (
    FinalPrompt,
    PromptComponents,
    PromptContribution,
    PromptPack,
)
from src.prompt.optimizer import PromptOptimizer
from src.prompt.scorer import PromptScorer
from src.prompt.templates import (
    DEFAULT_TEMPLATE,
    POSITIVE_SECTION_ORDER,
    PromptTemplate,
)
from src.prompt.variants import (
    VARIANT_STYLE_PROFILES,
    PromptVariant,
    VariantStyleProfile,
)

__all__ = [
    "DEFAULT_TEMPLATE",
    "POSITIVE_SECTION_ORDER",
    "VARIANT_STYLE_PROFILES",
    "FinalPrompt",
    "PromptBuilder",
    "PromptComposer",
    "PromptComponents",
    "PromptContribution",
    "PromptOptimizer",
    "PromptPack",
    "PromptScorer",
    "PromptTemplate",
    "PromptVariant",
    "VariantStyleProfile",
    "apply_contribution",
    "dedupe_preserve_order",
    "merge_csv_text",
    "merge_quality_tags",
    "normalize_components",
    "normalize_whitespace",
]
