"""Unit tests for the Prompt Optimization Engine."""

from __future__ import annotations

import pytest

from src.domain.config_loader import ConfigLoader
from src.domain.models import DomainType
from src.models.storyboard import Scene
from src.prompt import (
    VARIANT_STYLE_PROFILES,
    PromptComposer,
    PromptOptimizer,
    PromptScorer,
    PromptVariant,
)


def _scene() -> Scene:
    return Scene(
        id=1,
        title="Ottoman siege camp",
        description=(
            "Outside the Theodosian Walls at dawn. "
            "Gunners prepare the great bombard. "
            "Banners snap in the cold wind."
        ),
    )


class TestPromptOptimizer:
    def test_generates_three_named_variants_sorted_by_score(self) -> None:
        domain = ConfigLoader().load(DomainType.HISTORY)
        optimizer = PromptOptimizer(composer=PromptComposer())
        variants = optimizer.optimize(_scene(), domain)

        assert len(variants) == 3
        names = {item.style_name for item in variants}
        assert names == {"Cinematic", "Documentary", "Dramatic"}
        scores = [float(item.metadata["score"]) for item in variants]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 <= score <= 100.0 for score in scores)

    def test_variants_differ_in_camera_lighting_composition_wording(self) -> None:
        domain = ConfigLoader().load(DomainType.HISTORY)
        variants = PromptOptimizer().optimize(_scene(), domain)
        by_name = {item.style_name: item for item in variants}

        cinematic = by_name["Cinematic"].positive_prompt
        documentary = by_name["Documentary"].positive_prompt
        dramatic = by_name["Dramatic"].positive_prompt

        assert cinematic != documentary != dramatic
        assert "cinematic portrayal" in cinematic.lower()
        assert "observational documentary" in documentary.lower()
        assert "intensely dramatic" in dramatic.lower()
        assert "anamorphic" in cinematic.lower() or "dolly" in cinematic.lower()
        assert "eye-level" in documentary.lower() or "observational" in documentary.lower()
        assert "low-angle" in dramatic.lower() or "chiaroscuro" in dramatic.lower()

    def test_preserves_scene_meaning(self) -> None:
        domain = ConfigLoader().load(DomainType.SCIFI)
        scene = Scene(
            id=2,
            title="Mars habitat crew",
            description="Inside a pressurized dome. Engineers repair an airlock.",
        )
        variants = PromptOptimizer().optimize(
            scene,
            domain,
            subject="Mars habitat crew",
            environment="pressurized dome",
            action="engineers repair an airlock",
        )
        for variant in variants:
            assert variant.metadata["preserved_subject"] == "Mars habitat crew"
            assert "mars habitat crew" in variant.positive_prompt.lower()
            assert "pressurized dome" in variant.positive_prompt.lower()
            assert "airlock" in variant.positive_prompt.lower()

    def test_uses_domain_negative_and_style_pack(self) -> None:
        domain = ConfigLoader().load(DomainType.FINANCE)
        variants = PromptOptimizer().optimize(_scene(), domain)
        top = variants[0]
        style_token = domain.style.split(",")[0].strip()
        assert style_token in top.positive_prompt
        neg_token = domain.negative_prompt.split(",")[0].strip()
        assert neg_token.lower() in top.negative_prompt.lower()

    def test_rejects_bad_inputs(self) -> None:
        domain = ConfigLoader().load(DomainType.GENERAL)
        optimizer = PromptOptimizer()
        with pytest.raises(TypeError):
            optimizer.optimize("not a scene", domain)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            optimizer.optimize(_scene(), "not domain")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            optimizer.optimize(
                Scene(id=1, title="   ", description="x"),
                domain,
            )


class TestPromptScorer:
    def test_score_bounds_and_breakdown(self) -> None:
        domain = ConfigLoader().load(DomainType.HISTORY)
        scorer = PromptScorer(domain_context=domain)
        variant = PromptVariant(
            id="t1",
            style_name="Cinematic",
            positive_prompt=(
                "siege camp, wide anamorphic framing, dramatic cinematic key light, "
                "rule of thirds, layered depth, period-accurate costumes"
            ),
            negative_prompt=domain.negative_prompt,
            metadata={},
        )
        score = scorer.score(variant)
        assert 0.0 <= score <= 100.0
        assert "score_breakdown" in variant.metadata
        breakdown = variant.metadata["score_breakdown"]
        for key in (
            "clarity",
            "visual_specificity",
            "camera_usage",
            "composition",
            "lighting",
            "domain_consistency",
            "duplicate_wording",
        ):
            assert key in breakdown

    def test_empty_prompt_scores_low(self) -> None:
        scorer = PromptScorer()
        variant = PromptVariant(
            id="empty",
            style_name="Documentary",
            positive_prompt="",
            negative_prompt="",
            metadata={},
        )
        assert scorer.score(variant) < 20.0

    def test_duplicate_wording_penalized(self) -> None:
        scorer = PromptScorer()
        clean = PromptVariant(
            id="clean",
            style_name="Cinematic",
            positive_prompt="knight, castle courtyard, golden hour light, wide shot",
            negative_prompt="blurry",
            metadata={},
        )
        duped = PromptVariant(
            id="duped",
            style_name="Cinematic",
            positive_prompt=(
                "knight, knight, knight, castle courtyard, castle courtyard, "
                "golden hour light, golden hour light, wide shot, wide shot"
            ),
            negative_prompt="blurry",
            metadata={},
        )
        assert scorer.score(clean) > scorer.score(duped)


class TestVariantProfiles:
    def test_default_profiles_are_three(self) -> None:
        assert len(VARIANT_STYLE_PROFILES) == 3
        assert [p.style_name for p in VARIANT_STYLE_PROFILES] == [
            "Cinematic",
            "Documentary",
            "Dramatic",
        ]
