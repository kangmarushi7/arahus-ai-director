"""Unit tests for the Prompt Composition Engine."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from src.domain.config_loader import ConfigLoader
from src.domain.models import DomainType
from src.domain.prompt_context import DomainPromptContext
from src.prompt import (
    POSITIVE_SECTION_ORDER,
    FinalPrompt,
    PromptBuilder,
    PromptComposer,
    PromptComponents,
    PromptContribution,
    PromptTemplate,
    dedupe_preserve_order,
    merge_csv_text,
)
from src.prompt.models import PromptPack


class _StylePack:
    name = "style_pack"

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        return PromptContribution(
            style="oil painting",
            quality_tags=["masterpiece"],
            metadata={"style_pack": True},
        )


class _CameraPack:
    name = "camera_pack"

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        return PromptContribution(
            camera="85mm lens",
            metadata={"camera_pack": True},
        )


class TestDedupeAndNormalize:
    def test_duplicate_removal_case_insensitive(self) -> None:
        assert dedupe_preserve_order(
            ["Sharp Focus", "soft light", "sharp focus", "  Soft Light  ", ""]
        ) == ["Sharp Focus", "soft light"]

    def test_merge_csv_dedupes_and_orders(self) -> None:
        assert merge_csv_text(
            "detailed, cinematic",
            "Cinematic, grain",
            "detailed",
        ) == "detailed, cinematic, grain"

    def test_whitespace_normalization(self) -> None:
        components = PromptComponents(
            subject="  Ottoman   emperor  ",
            action="rides\nhorse",
            quality_tags=["  highly   detailed ", "sharp focus"],
        )
        assert components.subject == "Ottoman emperor"
        assert components.action == "rides horse"
        assert components.quality_tags == ["highly detailed", "sharp focus"]


class TestOrdering:
    def test_positive_section_order_is_stable(self) -> None:
        composer = PromptComposer()
        result = composer.compose(
            PromptComponents(
                subject="knight",
                environment="castle courtyard",
                action="drawing sword",
                camera="35mm",
                lighting="golden hour",
                composition="rule of thirds",
                style="cinematic",
                extra_details="mud on boots",
                quality_tags=["detailed", "sharp"],
            )
        )
        positive = result.positive_prompt
        positions = [
            positive.index(token)
            for token in [
                "knight",
                "drawing sword",
                "castle courtyard",
                "35mm",
                "golden hour",
                "rule of thirds",
                "cinematic",
                "mud on boots",
                "detailed",
            ]
        ]
        assert positions == sorted(positions)
        assert result.metadata["section_order"] == list(POSITIVE_SECTION_ORDER)

    def test_custom_template_changes_order(self) -> None:
        template = PromptTemplate(
            section_order=("style", "subject", "camera"),
            separator=" | ",
        )
        composer = PromptComposer(template=template)
        result = composer.compose(
            PromptComponents(subject="hero", camera="wide", style="noir")
        )
        assert result.positive_prompt == "noir | hero | wide"


class TestDomainMerge:
    def test_compose_from_domain_merges_history_yaml(self) -> None:
        domain = ConfigLoader(cache_enabled=True).load(DomainType.HISTORY)
        composer = PromptComposer()
        result = composer.compose_from_domain(
            domain,
            subject="Mehmed II",
            environment="walls of Constantinople",
            action="surveying the siege",
        )

        assert isinstance(result, FinalPrompt)
        assert "Mehmed II" in result.positive_prompt
        assert "surveying the siege" in result.positive_prompt
        assert "walls of Constantinople" in result.positive_prompt
        assert domain.camera.split(",")[0].strip() in result.positive_prompt
        assert "period" in result.positive_prompt.lower() or "historical" in (
            result.positive_prompt.lower()
        )
        for tag in domain.quality_tags:
            assert tag in result.positive_prompt
        assert "modern clothing" in result.negative_prompt.lower()
        assert result.metadata["domain"] == "history"
        assert result.metadata["image_defaults"]["width"] == 1024

    def test_domain_color_palette_merges_into_style(self) -> None:
        domain = DomainPromptContext(
            domain=DomainType.GENERAL,
            style="cinematic realism",
            camera="35mm",
            lighting="soft light",
            composition="centered",
            color_palette="muted earth tones",
            quality_tags=["detailed"],
            negative_prompt="blurry",
            image_defaults={},
            video_defaults={},
        )
        result = PromptComposer().compose_from_domain(
            domain,
            subject="traveler",
        )
        assert "cinematic realism" in result.positive_prompt
        assert "muted earth tones" in result.positive_prompt

    def test_packs_apply_after_domain(self) -> None:
        domain = DomainPromptContext(
            domain=DomainType.SCIFI,
            style="futuristic",
            camera="anamorphic",
            lighting="neon",
            composition="wide",
            quality_tags=["detailed"],
            negative_prompt="medieval",
            image_defaults={},
            video_defaults={},
        )
        composer = PromptComposer(packs=[_StylePack(), _CameraPack()])
        result = composer.compose_from_domain(
            domain,
            subject="astronaut",
            environment="Mars habitat",
            action="checking instruments",
        )
        assert "oil painting" in result.positive_prompt
        assert "85mm lens" in result.positive_prompt
        assert "masterpiece" in result.positive_prompt
        assert result.metadata["packs_applied"] == ["style_pack", "camera_pack"]
        assert result.metadata["style_pack"] is True
        assert result.metadata["camera_pack"] is True


class TestMissingAndEmpty:
    def test_missing_optional_fields_omitted_from_positive(self) -> None:
        result = PromptComposer().compose(
            PromptComponents(subject="lone tree")
        )
        assert result.positive_prompt == "lone tree"
        assert result.negative_prompt == ""
        assert result.metadata["sections_used"] == ["subject"]

    def test_empty_strings_ignored(self) -> None:
        result = PromptComposer().compose(
            PromptComponents(
                subject="castle",
                environment="",
                action="   ",
                camera="",
                lighting="",
                composition="",
                style="",
                extra_details="",
                quality_tags=[],
                negative_prompt="",
            )
        )
        assert result.positive_prompt == "castle"

    def test_empty_subject_with_other_fields(self) -> None:
        result = PromptComposer().compose(
            PromptComponents(camera="drone shot", style="documentary")
        )
        assert result.positive_prompt == "drone shot, documentary"
        assert "subject" not in result.metadata["sections_used"]

    def test_duplicate_quality_tags_removed(self) -> None:
        result = PromptComposer().compose(
            PromptComponents(
                subject="ship",
                quality_tags=["detailed", "Detailed", "sharp", "detailed"],
            )
        )
        assert result.positive_prompt == "ship, detailed, sharp"
        assert result.metadata["quality_tags"] == ["detailed", "sharp"]

    def test_duplicate_negatives_removed_on_merge(self) -> None:
        builder = PromptBuilder(
            PromptComponents(negative_prompt="blurry, watermark")
        )
        builder.merge(PromptContribution(negative_prompt="Watermark, low quality"))
        assert builder.build().negative_prompt == "blurry, watermark, low quality"


class TestComposerGuards:
    def test_compose_rejects_non_components(self) -> None:
        with pytest.raises(TypeError, match="PromptComponents"):
            PromptComposer().compose("not components")  # type: ignore[arg-type]

    def test_compose_from_domain_rejects_bad_context(self) -> None:
        with pytest.raises(TypeError, match="DomainPromptContext"):
            PromptComposer().compose_from_domain(
                "nope",  # type: ignore[arg-type]
                subject="x",
            )

    def test_prompt_pack_protocol_accepted(self) -> None:
        pack: PromptPack = _StylePack()
        assert pack.name == "style_pack"
