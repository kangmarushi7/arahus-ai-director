"""Prompt optimization: generate, score, and rank prompt variants."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.domain.prompt_context import DomainPromptContext
from src.models.storyboard import Scene
from src.prompt.builder import PromptBuilder
from src.prompt.composer import PromptComposer
from src.prompt.models import PromptComponents, PromptContribution
from src.prompt.scorer import PromptScorer
from src.prompt.variants import (
    VARIANT_STYLE_PROFILES,
    PromptVariant,
    VariantStyleProfile,
    frame_action,
    frame_subject,
    new_variant_id,
)

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """Generate scored prompt variants for a scene before rendering.

    Uses :class:`PromptComposer` for deterministic assembly and
    :class:`PromptScorer` for ranking. Does not call an LLM or generate images.
    """

    def __init__(
        self,
        *,
        composer: PromptComposer | None = None,
        scorer: PromptScorer | None = None,
        profiles: Sequence[VariantStyleProfile] | None = None,
    ) -> None:
        """Wire composer, scorer, and style profiles via dependency injection.

        Args:
            composer: Prompt assembly engine (defaults to a fresh composer).
            scorer: Variant scorer. When omitted, a scorer is created per
                optimize call bound to the provided domain context.
            profiles: Style profiles to generate. Defaults to Cinematic,
                Documentary, and Dramatic.
        """
        self._composer = composer or PromptComposer()
        self._scorer = scorer
        self._profiles: tuple[VariantStyleProfile, ...] = tuple(
            profiles or VARIANT_STYLE_PROFILES
        )
        if len(self._profiles) < 1:
            raise ValueError("profiles must contain at least one VariantStyleProfile")

    @property
    def composer(self) -> PromptComposer:
        """Injected :class:`PromptComposer`."""
        return self._composer

    def optimize(
        self,
        scene: Scene,
        domain_context: DomainPromptContext,
        *,
        subject: str | None = None,
        environment: str | None = None,
        action: str | None = None,
    ) -> list[PromptVariant]:
        """Build, score, and return prompt variants sorted best-first.

        Args:
            scene: Storyboard scene (meaning taken from title/description unless
                explicit subject/environment/action overrides are provided).
            domain_context: Domain YAML prompt defaults.
            subject: Optional subject override.
            environment: Optional environment override.
            action: Optional action override.

        Returns:
            :class:`PromptVariant` list sorted by descending score.

        Raises:
            TypeError: If ``scene`` or ``domain_context`` has the wrong type.
            ValueError: If scene meaning cannot be derived (empty subject).
        """
        if not isinstance(scene, Scene):
            raise TypeError("scene must be a Scene instance")
        if not isinstance(domain_context, DomainPromptContext):
            raise TypeError("domain_context must be a DomainPromptContext")

        meaning = self._extract_scene_meaning(
            scene,
            subject=subject,
            environment=environment,
            action=action,
        )
        scorer = self._scorer or PromptScorer(domain_context=domain_context)

        variants: list[PromptVariant] = []
        for profile in self._profiles:
            variant = self._build_variant(
                profile=profile,
                domain_context=domain_context,
                scene=scene,
                meaning=meaning,
            )
            score = scorer.score(variant)
            variant.metadata["score"] = score
            variants.append(variant)
            logger.info(
                "event=prompt_variant_scored scene_id=%s style=%s score=%.2f",
                scene.id,
                profile.style_name,
                score,
            )

        variants.sort(
            key=lambda item: float(item.metadata.get("score", 0.0)),
            reverse=True,
        )
        return variants

    def _build_variant(
        self,
        *,
        profile: VariantStyleProfile,
        domain_context: DomainPromptContext,
        scene: Scene,
        meaning: dict[str, str],
    ) -> PromptVariant:
        """Compose one style variant while preserving scene meaning."""
        framed_subject = frame_subject(profile, meaning["subject"])
        framed_action = frame_action(profile, meaning["action"])

        # Domain defaults via PromptComposer, then style-profile overlays.
        domain_final = self._composer.compose_from_domain(
            domain_context,
            subject=framed_subject or meaning["subject"],
            environment=meaning["environment"],
            action=framed_action or meaning["action"],
            extra_details=meaning["extra_details"],
            quality_tags=list(profile.quality_tags),
            negative_prompt=profile.negative_overlay,
            metadata={
                "scene_id": scene.id,
                "scene_title": scene.title,
                "variant_style": profile.style_name,
                "source": "prompt_optimizer",
            },
        )

        # Re-compose with explicit camera/lighting/composition/style overlays so
        # variants differ beyond domain defaults while meaning stays intact.
        components = PromptBuilder(
            PromptComponents(
                subject=framed_subject or meaning["subject"],
                environment=meaning["environment"],
                action=framed_action or meaning["action"],
                camera=domain_context.camera,
                lighting=domain_context.lighting,
                composition=domain_context.composition,
                style=", ".join(
                    part
                    for part in (domain_context.style, domain_context.color_palette)
                    if part.strip()
                ),
                quality_tags=list(domain_context.quality_tags),
                negative_prompt=domain_context.negative_prompt,
                extra_details=meaning["extra_details"],
            )
        ).merge(
            PromptContribution(
                camera=profile.camera_overlay,
                lighting=profile.lighting_overlay,
                composition=profile.composition_overlay,
                style=profile.style_overlay,
                quality_tags=list(profile.quality_tags),
                negative_prompt=profile.negative_overlay,
            )
        ).build()

        final = self._composer.compose(
            components,
            context={"domain": domain_context.domain.value},
            metadata={
                "scene_id": scene.id,
                "scene_title": scene.title,
                "variant_style": profile.style_name,
                "source": "prompt_optimizer",
                "domain_compose_chars": len(domain_final.positive_prompt),
            },
        )

        return PromptVariant(
            id=new_variant_id(profile.style_name),
            style_name=profile.style_name,
            positive_prompt=final.positive_prompt,
            negative_prompt=final.negative_prompt,
            metadata={
                **final.metadata,
                "scene_id": scene.id,
                "scene_title": scene.title,
                "domain": domain_context.domain.value,
                "preserved_subject": meaning["subject"],
                "preserved_environment": meaning["environment"],
                "preserved_action": meaning["action"],
            },
        )

    @staticmethod
    def _extract_scene_meaning(
        scene: Scene,
        *,
        subject: str | None,
        environment: str | None,
        action: str | None,
    ) -> dict[str, str]:
        """Derive subject / environment / action while preserving meaning."""
        resolved_subject = (subject if subject is not None else scene.title).strip()
        if not resolved_subject:
            raise ValueError("scene subject/title must be a non-empty string")

        description = (scene.description or "").strip()
        resolved_environment = environment.strip() if environment is not None else ""
        resolved_action = action.strip() if action is not None else ""

        extra = description
        if environment is None and action is None and description:
            parts = [part.strip() for part in description.replace("!", ".").split(".")]
            parts = [part for part in parts if part]
            if parts:
                resolved_environment = parts[0]
                if len(parts) > 1:
                    resolved_action = parts[1]
                    extra = ". ".join(parts[2:]).strip() if len(parts) > 2 else ""

        return {
            "subject": " ".join(resolved_subject.split()),
            "environment": " ".join(resolved_environment.split()),
            "action": " ".join(resolved_action.split()),
            "extra_details": " ".join(extra.split()),
        }
