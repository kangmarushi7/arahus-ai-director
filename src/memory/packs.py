"""PromptPacks that inject Character / World / Style memory into composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.models.memory import ProjectMemory, SceneContinuityMeta
from src.models.scene_plan import ScenePlan
from src.prompt.models import PromptComponents, PromptContribution, PromptPack


class CharacterBiblePack:
    """Inject CharacterBible identity into subject / negatives."""

    name = "character_bible"

    def __init__(self, memory: ProjectMemory) -> None:
        self._memory = memory

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        if not self._memory.characters:
            return PromptContribution()
        fragments = [
            character.to_prompt_fragment() for character in self._memory.characters
        ]
        negatives: list[str] = []
        for character in self._memory.characters:
            negatives.extend(character.negative)
        return PromptContribution(
            subject=", ".join(fragments),
            negative_prompt=", ".join(negatives),
            metadata={
                "character_asset_ids": [
                    character.asset_id for character in self._memory.characters
                ],
            },
        )


class WorldBiblePack:
    """Inject WorldBible location / era into environment."""

    name = "world_bible"

    def __init__(self, memory: ProjectMemory) -> None:
        self._memory = memory

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        fragment = self._memory.world.to_prompt_fragment()
        if not fragment:
            return PromptContribution()
        return PromptContribution(
            environment=fragment,
            metadata={
                "location_asset_ids": [
                    location.asset_id for location in self._memory.world.locations
                ],
                "primary_location_id": self._memory.world.primary_location_id,
            },
        )


class StyleBiblePack:
    """Inject StyleBible aesthetic into style / camera / lighting / quality."""

    name = "style_bible"

    def __init__(self, memory: ProjectMemory) -> None:
        self._memory = memory

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        style = self._memory.style
        quality_tags = [
            part.strip()
            for part in style.quality.split(",")
            if part.strip()
        ]
        style_parts = [
            part for part in (style.visual_style, style.color_palette) if part.strip()
        ]
        camera_parts = [part for part in (style.camera, style.lens) if part.strip()]
        return PromptContribution(
            style=", ".join(style_parts),
            camera=", ".join(camera_parts),
            lighting=style.lighting,
            quality_tags=quality_tags,
            metadata={
                "style_asset_id": style.asset_id,
                "style_bible_id": style.id,
            },
        )


class ContinuityPack:
    """Inject SceneContinuityMeta keep/change directives into extras."""

    name = "scene_continuity"

    def __init__(self, meta: SceneContinuityMeta | None) -> None:
        self._meta = meta

    def contribute(
        self,
        components: PromptComponents,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PromptContribution:
        if self._meta is None:
            return PromptContribution()
        fragment = self._meta.to_prompt_fragment()
        if not fragment:
            return PromptContribution()
        return PromptContribution(
            extra_details=fragment,
            metadata={
                "previous_scene": self._meta.previous_scene,
                "keep": list(self._meta.keep),
                "change": list(self._meta.change),
            },
        )


def build_memory_packs(
    memory: ProjectMemory | None,
    *,
    scene_plan: ScenePlan | None = None,
) -> list[PromptPack]:
    """Build ordered PromptPacks for project memory (+ optional scene continuity)."""
    packs: list[PromptPack] = []
    if memory is not None:
        packs.extend(
            [
                CharacterBiblePack(memory),
                WorldBiblePack(memory),
                StyleBiblePack(memory),
            ]
        )
    if scene_plan is not None and scene_plan.continuity_meta is not None:
        packs.append(ContinuityPack(scene_plan.continuity_meta))
    return packs


def composer_with_memory(
    base_packs: Sequence[PromptPack] | None,
    memory: ProjectMemory | None,
    *,
    scene_plan: ScenePlan | None = None,
) -> list[PromptPack]:
    """Merge existing composer packs with memory packs (memory last)."""
    return list(base_packs or []) + build_memory_packs(memory, scene_plan=scene_plan)
