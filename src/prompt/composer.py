"""Deterministic PromptComposer — no LLM calls."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from src.domain.prompt_context import DomainPromptContext
from src.prompt.builder import PromptBuilder, normalize_components
from src.prompt.models import (
    FinalPrompt,
    PromptComponents,
    PromptContribution,
    PromptPack,
)
from src.prompt.templates import DEFAULT_TEMPLATE, PromptTemplate

if TYPE_CHECKING:
    from src.models.memory import ProjectMemory

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

    def with_packs(self, packs: Sequence[PromptPack]) -> PromptComposer:
        """Return a composer that applies ``packs`` after existing ones."""
        return PromptComposer(
            template=self._template,
            packs=[*self._packs, *packs],
        )

    def _composer_for_memory(
        self,
        project_memory: ProjectMemory | None,
        *,
        scene_plan: Any = None,
    ) -> PromptComposer:
        """Attach Character/World/Style/Continuity packs when memory is present."""
        if project_memory is None and scene_plan is None:
            return self
        from src.memory.packs import build_memory_packs

        packs = build_memory_packs(project_memory, scene_plan=scene_plan)
        if not packs:
            return self
        return self.with_packs(packs)

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
        project_memory: ProjectMemory | None = None,
    ) -> FinalPrompt:
        """Build a prompt by merging domain YAML defaults with scene fields.

        Domain camera, lighting, composition, style, color palette, quality
        tags, and negative prompts are applied first; caller overrides and
        injected packs merge on top. When ``project_memory`` is provided,
        CharacterBible / WorldBible / StyleBible packs are applied automatically.

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
            project_memory: Optional project Character/World/Style memory.

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

        composer = self._composer_for_memory(project_memory)
        return composer.compose(base, context=pack_context, metadata=meta)

    def compose_from_scene_plan(
        self,
        scene_plan: Any,
        domain_context: DomainPromptContext | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        project_memory: ProjectMemory | None = None,
    ) -> FinalPrompt:
        """Convert a cinematic :class:`ScenePlan` into a model-specific prompt.

        Merges ScenePlan camera / lighting / composition / emotion / continuity
        / negative_prompt with optional domain YAML defaults. Automatically
        injects CharacterBible / WorldBible / StyleBible / continuity packs when
        ``project_memory`` (and scene continuity_meta) are provided.

        Args:
            scene_plan: :class:`~src.models.scene_plan.ScenePlan` instance.
            domain_context: Optional domain defaults layered underneath.
            context: Optional pack context.
            metadata: Extra result metadata.
            project_memory: Optional project Character/World/Style memory.

        Returns:
            Deterministic :class:`FinalPrompt`.
        """
        from src.models.scene_plan import ScenePlan

        if not isinstance(scene_plan, ScenePlan):
            raise TypeError("scene_plan must be a ScenePlan instance")

        subject = scene_plan.subject.strip() or scene_plan.title
        environment = scene_plan.environment
        action = scene_plan.action.strip() or scene_plan.description
        camera = scene_plan.camera_directive()
        lighting = scene_plan.lighting
        composition = scene_plan.composition

        extra_parts = [
            part
            for part in (scene_plan.emotion, scene_plan.continuity)
            if part.strip()
        ]
        # Prefer the narrative description as extra detail when subject/action
        # already cover the beats.
        if scene_plan.description.strip() and scene_plan.action.strip():
            extra_parts.insert(0, scene_plan.description)
        extra_details = ", ".join(extra_parts)

        if domain_context is not None:
            # Domain defaults first; ScenePlan cinematic fields override via merge.
            style_parts = [domain_context.style]
            if domain_context.color_palette.strip():
                style_parts.append(domain_context.color_palette)
            base = PromptComponents(
                subject=subject,
                environment=environment or "",
                action=action,
                camera=camera or domain_context.camera,
                lighting=lighting or domain_context.lighting,
                composition=composition or domain_context.composition,
                style=", ".join(part for part in style_parts if part.strip()),
                quality_tags=list(domain_context.quality_tags),
                negative_prompt=domain_context.negative_prompt,
                extra_details=extra_details,
            )
            # Explicit ScenePlan camera/lighting/composition win when set.
            overrides = PromptContribution(
                camera=camera,
                lighting=lighting,
                composition=composition,
                negative_prompt=scene_plan.negative_prompt,
            )
            base = PromptBuilder(base).merge(overrides).build()
            pack_context = {"domain": domain_context.domain.value, "source": "scene_plan"}
            meta: dict[str, Any] = {
                "domain": domain_context.domain.value,
                "source": "compose_from_scene_plan",
                "scene_id": scene_plan.id,
                "scene_title": scene_plan.title,
                "camera_shot": scene_plan.camera_shot,
                "camera_movement": scene_plan.camera_movement,
                "camera_angle": scene_plan.camera_angle,
                "lens": scene_plan.lens,
                "emotion": scene_plan.emotion,
                "continuity": scene_plan.continuity,
            }
        else:
            base = PromptComponents(
                subject=subject,
                environment=environment,
                action=action,
                camera=camera,
                lighting=lighting,
                composition=composition,
                extra_details=extra_details,
                negative_prompt=scene_plan.negative_prompt,
            )
            pack_context = {"source": "scene_plan"}
            meta = {
                "source": "compose_from_scene_plan",
                "scene_id": scene_plan.id,
                "scene_title": scene_plan.title,
                "camera_shot": scene_plan.camera_shot,
                "camera_movement": scene_plan.camera_movement,
                "camera_angle": scene_plan.camera_angle,
                "lens": scene_plan.lens,
                "emotion": scene_plan.emotion,
                "continuity": scene_plan.continuity,
            }

        if scene_plan.continuity_meta is not None:
            meta["continuity_meta"] = scene_plan.continuity_meta.to_dict()
        if project_memory is not None:
            meta["project_id"] = project_memory.project_id

        if context:
            pack_context.update(dict(context))
        if metadata:
            meta.update(dict(metadata))

        composer = self._composer_for_memory(
            project_memory,
            scene_plan=scene_plan,
        )
        return composer.compose(base, context=pack_context, metadata=meta)
