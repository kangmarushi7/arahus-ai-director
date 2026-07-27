"""Deterministic PromptComposer — no LLM calls."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from src.domain.prompt_context import DomainPromptContext
from src.prompt.builder import PromptBuilder, normalize_components
from src.prompt.models import (
    FinalPrompt,
    PromptComponents,
    PromptContribution,
    PromptPack,
)
from src.prompt.templates import DEFAULT_TEMPLATE, PromptTemplate

logger = logging.getLogger(__name__)


class PromptComposer:
    """Build :class:`FinalPrompt` values from structured components.

    Pure deterministic merge/render logic. Packs (style, camera, character,
    knowledge, assets) are injected via the :class:`PromptPack` protocol so
    new sources can be added without changing this class.
    """

    def __init__(
        self,
        *,
        template: PromptTemplate | None = None,
        packs: Sequence[PromptPack] | None = None,
    ) -> None:
        """Configure template and injectable packs.

        Args:
            template: Section order / separators. Defaults to
                :data:`~src.prompt.templates.DEFAULT_TEMPLATE`.
            packs: Optional ordered contributions applied after the base
                components (and after domain defaults for
                :meth:`compose_from_domain`).
        """
        self._template = template or DEFAULT_TEMPLATE
        self._packs: list[PromptPack] = list(packs or [])

    @property
    def template(self) -> PromptTemplate:
        """Active render template."""
        return self._template

    @property
    def packs(self) -> tuple[PromptPack, ...]:
        """Injected packs in application order."""
        return tuple(self._packs)

    def compose(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> FinalPrompt:
        """Merge packs into ``components`` and render a :class:`FinalPrompt`.

        Args:
            components: Base structured prompt parts.
            context: Optional free-form context forwarded to packs.
            metadata: Extra metadata merged into the result.

        Returns:
            Deterministic positive/negative prompts plus metadata.
        """
        if not isinstance(components, PromptComponents):
            raise TypeError("components must be a PromptComponents instance")

        builder = PromptBuilder(components)
        applied_packs: list[str] = []
        pack_context = dict(context or {})

        for pack in self._packs:
            contribution = pack.contribute(builder.components, context=pack_context)
            if not isinstance(contribution, PromptContribution):
                raise TypeError(
                    f"PromptPack {pack.name!r} must return PromptContribution, "
                    f"got {type(contribution).__name__}"
                )
            builder.merge(contribution)
            applied_packs.append(pack.name)

        merged = normalize_components(builder.build())
        positive = self._template.render_positive(merged)
        negative = merged.negative_prompt

        result_metadata: dict[str, Any] = {
            "section_order": list(self._template.section_order),
            "sections_used": [name for name, _ in self._template.sections(merged)],
            "packs_applied": applied_packs,
            "quality_tags": list(merged.quality_tags),
        }
        result_metadata.update(builder.metadata)
        if metadata:
            result_metadata.update(dict(metadata))

        final = FinalPrompt(
            positive_prompt=positive,
            negative_prompt=negative,
            metadata=result_metadata,
        )
        logger.debug(
            "event=prompt_composed positive_chars=%s negative_chars=%s packs=%s",
            len(final.positive_prompt),
            len(final.negative_prompt),
            applied_packs,
        )
        return final

    def compose_from_domain(
        self,
        domain_context: DomainPromptContext,
        subject: str,
        environment: str = "",
        action: str = "",
        *,
        extra_details: str = "",
        quality_tags: Sequence[str] | None = None,
        negative_prompt: str = "",
        context: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> FinalPrompt:
        """Build a prompt by merging domain YAML defaults with scene fields.

        Domain camera, lighting, composition, style, color palette, quality
        tags, and negative prompts are applied first; caller overrides and
        injected packs merge on top.

        Args:
            domain_context: YAML-backed :class:`DomainPromptContext`.
            subject: Primary subject of the shot.
            environment: Setting / location.
            action: What is happening in the frame.
            extra_details: Optional additional positive details.
            quality_tags: Extra tags merged after domain tags.
            negative_prompt: Extra negatives merged after domain negatives.
            context: Optional pack context.
            metadata: Extra result metadata.

        Returns:
            Deterministic :class:`FinalPrompt`.
        """
        if not isinstance(domain_context, DomainPromptContext):
            raise TypeError("domain_context must be a DomainPromptContext")

        style_parts = [domain_context.style]
        if domain_context.color_palette.strip():
            style_parts.append(domain_context.color_palette)

        base = PromptComponents(
            subject=subject,
            environment=environment,
            action=action,
            camera=domain_context.camera,
            lighting=domain_context.lighting,
            composition=domain_context.composition,
            style=", ".join(part for part in style_parts if part.strip()),
            quality_tags=list(domain_context.quality_tags),
            negative_prompt=domain_context.negative_prompt,
            extra_details=extra_details,
        )

        if quality_tags:
            base = PromptBuilder(base).merge(
                PromptContribution(quality_tags=list(quality_tags))
            ).build()
        if negative_prompt.strip():
            base = PromptBuilder(base).merge(
                PromptContribution(negative_prompt=negative_prompt)
            ).build()

        pack_context = {"domain": domain_context.domain.value}
        if context:
            pack_context.update(dict(context))

        meta = {
            "domain": domain_context.domain.value,
            "source": "compose_from_domain",
            "image_defaults": dict(domain_context.image_defaults),
            "video_defaults": dict(domain_context.video_defaults),
        }
        if metadata:
            meta.update(dict(metadata))

        return self.compose(base, context=pack_context, metadata=meta)
