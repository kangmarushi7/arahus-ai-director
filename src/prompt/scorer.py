"""Deterministic scoring for prompt variants (no LLM, no image generation)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from src.prompt.builder import normalize_whitespace, split_csv_phrases

if TYPE_CHECKING:
    from src.domain.prompt_context import DomainPromptContext
    from src.prompt.variants import PromptVariant

_CAMERA_TERMS = frozenset(
    {
        "camera",
        "lens",
        "mm",
        "anamorphic",
        "dolly",
        "tracking",
        "handheld",
        "tripod",
        "close-up",
        "closeup",
        "wide",
        "medium",
        "aerial",
        "crane",
        "orbital",
        "framing",
        "depth",
        "field",
        "angle",
        "shot",
        "bokeh",
        "focal",
    }
)
_COMPOSITION_TERMS = frozenset(
    {
        "composition",
        "thirds",
        "leading",
        "silhouette",
        "foreground",
        "background",
        "depth",
        "symmetry",
        "centered",
        "hierarchy",
        "negative",
        "space",
        "scale",
        "layer",
        "layered",
        "balanced",
        "perspective",
    }
)
_LIGHTING_TERMS = frozenset(
    {
        "light",
        "lighting",
        "shadow",
        "shadows",
        "rim",
        "key",
        "fill",
        "haze",
        "volumetric",
        "contrast",
        "highlight",
        "highlights",
        "chiaroscuro",
        "glow",
        "illumination",
        "daylight",
        "practical",
        "practicals",
        "soft",
        "hard",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text or "")]


def _clamp(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, score))


def _term_coverage(text: str, lexicon: Iterable[str]) -> float:
    """Return 0–100 based on how many lexicon terms appear in ``text``."""
    words = set(_tokens(text))
    hits = sum(1 for term in lexicon if term in words or term in text.casefold())
    if hits <= 0:
        return 0.0
    if hits == 1:
        return 45.0
    if hits == 2:
        return 70.0
    if hits == 3:
        return 85.0
    return 95.0


class PromptScorer:
    """Score :class:`PromptVariant` quality on a 0–100 scale.

    Pure heuristic evaluation — no LLM and no image generation. Optional
    :class:`~src.domain.prompt_context.DomainPromptContext` improves the
    domain-consistency signal.
    """

    def __init__(
        self,
        *,
        domain_context: DomainPromptContext | None = None,
    ) -> None:
        """Optionally bind domain context used for consistency checks.

        Args:
            domain_context: YAML domain defaults; when omitted, domain
                consistency is scored from generic visual language only.
        """
        self._domain_context = domain_context

    def score(self, variant: PromptVariant) -> float:
        """Evaluate ``variant`` and return a score in ``[0, 100]``.

        Criteria (weighted):
            * clarity
            * visual specificity
            * camera usage
            * composition
            * lighting
            * domain consistency
            * duplicate wording (penalty)
        """
        if variant is None:
            raise TypeError("variant is required")

        positive = normalize_whitespace(variant.positive_prompt)
        negative = normalize_whitespace(variant.negative_prompt)
        breakdown = {
            "clarity": self._score_clarity(positive),
            "visual_specificity": self._score_visual_specificity(positive),
            "camera_usage": _term_coverage(positive, _CAMERA_TERMS),
            "composition": _term_coverage(positive, _COMPOSITION_TERMS),
            "lighting": _term_coverage(positive, _LIGHTING_TERMS),
            "domain_consistency": self._score_domain_consistency(positive, negative),
            "duplicate_wording": self._score_duplicate_wording(positive),
        }

        # Duplicate wording is a penalty channel: map 100→no penalty, 0→full hit.
        duplicate_penalty = (100.0 - breakdown["duplicate_wording"]) * 0.35
        weighted = (
            breakdown["clarity"] * 0.18
            + breakdown["visual_specificity"] * 0.16
            + breakdown["camera_usage"] * 0.14
            + breakdown["composition"] * 0.14
            + breakdown["lighting"] * 0.14
            + breakdown["domain_consistency"] * 0.14
            + breakdown["duplicate_wording"] * 0.10
            - duplicate_penalty
        )
        total = round(_clamp(weighted), 2)
        # Attach breakdown for callers that inspect metadata after scoring.
        variant.metadata["score_breakdown"] = breakdown
        variant.metadata["score"] = total
        return total

    def _score_clarity(self, positive: str) -> float:
        if not positive:
            return 0.0
        length = len(positive)
        # Prefer informative but not bloated prompts.
        if length < 40:
            return 25.0
        if length < 80:
            return 55.0
        if length <= 600:
            return 90.0
        if length <= 900:
            return 70.0
        return 45.0

    def _score_visual_specificity(self, positive: str) -> float:
        phrases = split_csv_phrases(positive)
        if not phrases:
            return 0.0
        # Reward multiple concrete phrase segments and multi-word descriptors.
        multi_word = sum(1 for phrase in phrases if len(phrase.split()) >= 2)
        richness = (len(phrases) * 8.0) + (multi_word * 6.0)
        return _clamp(richness)

    def _score_domain_consistency(self, positive: str, negative: str) -> float:
        domain = self._domain_context
        if domain is None:
            # Neutral baseline when no domain is bound.
            return 60.0 if positive else 0.0

        haystack = f"{positive} {negative}".casefold()
        anchors = [
            *split_csv_phrases(domain.style)[:4],
            *split_csv_phrases(domain.camera)[:3],
            *split_csv_phrases(domain.lighting)[:3],
            *split_csv_phrases(domain.negative_prompt)[:4],
        ]
        anchors = [a for a in anchors if len(a) >= 4]
        if not anchors:
            return 50.0

        hits = sum(1 for anchor in anchors if anchor.casefold() in haystack)
        ratio = hits / max(1, len(anchors))
        return _clamp(35.0 + (ratio * 65.0))

    def _score_duplicate_wording(self, positive: str) -> float:
        """Higher is better: 100 means no harmful duplication."""
        phrases = [p.casefold() for p in split_csv_phrases(positive)]
        if not phrases:
            return 0.0
        unique = set(phrases)
        phrase_dup_ratio = 1.0 - (len(unique) / len(phrases))

        tokens = _tokens(positive)
        if len(tokens) < 4:
            token_penalty = 0.0
        else:
            counts: dict[str, int] = {}
            for token in tokens:
                if len(token) < 4:
                    continue
                counts[token] = counts.get(token, 0) + 1
            repeated = sum(count - 1 for count in counts.values() if count > 2)
            token_penalty = min(1.0, repeated / max(1, len(tokens) * 0.25))

        penalty = max(phrase_dup_ratio, token_penalty)
        return _clamp(100.0 * (1.0 - penalty))
