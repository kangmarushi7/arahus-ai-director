"""World Builder — construct Character / World / Style bibles from research."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.domain.models import DomainInfo
from src.domain.prompt_context import DomainPromptContext
from src.memory.ids import project_id_for_topic, slugify
from src.models.memory import (
    AppearanceBible,
    AssetKind,
    AssetRegistry,
    CharacterBible,
    LocationBible,
    ProjectMemory,
    StyleBible,
    UniformBible,
    WorldBible,
)
from src.models.research import ResearchResult

if TYPE_CHECKING:
    from src.memory.store import ProjectMemoryStore

logger = logging.getLogger(__name__)


def _clothing_primary(research: ResearchResult) -> str:
    if research.clothing:
        return research.clothing[0]
    return ""


def _architecture_text(research: ResearchResult) -> str:
    if research.architecture:
        return ", ".join(research.architecture[:3])
    return ""


class WorldBuilder:
    """Build and merge project memory without calling an LLM.

    Derives structured CharacterBible / WorldBible / StyleBible entries from
    research + domain defaults, assigning stable asset IDs via the registry.
    """

    def __init__(self, store: ProjectMemoryStore | None = None) -> None:
        from src.memory.store import ProjectMemoryStore as _Store

        self._store = store or _Store()

    @property
    def store(self) -> ProjectMemoryStore:
        return self._store

    def build(
        self,
        research: ResearchResult,
        *,
        domain_info: DomainInfo | None = None,
        prompt_context: DomainPromptContext | None = None,
        project_id: str | None = None,
        persist: bool = True,
        existing: ProjectMemory | None = None,
    ) -> ProjectMemory:
        """Create or refresh project memory for ``research.topic``."""
        if not isinstance(research, ResearchResult):
            raise TypeError("research must be a ResearchResult instance")

        resolved_id = project_id or project_id_for_topic(research.topic)
        base = existing
        if base is None:
            base = self._store.load(resolved_id)
        if base is None:
            base = ProjectMemory(project_id=resolved_id, topic=research.topic)
        else:
            base = base.model_copy(
                update={
                    "project_id": resolved_id,
                    "topic": research.topic or base.topic,
                }
            )

        registry = base.registry or AssetRegistry(project_id=resolved_id)
        if registry.project_id != resolved_id:
            registry = registry.model_copy(update={"project_id": resolved_id})

        characters = self._build_characters(research, registry, prior=base.characters)
        world = self._build_world(research, registry, prior=base.world)
        style = self._build_style(
            research,
            registry,
            domain_info=domain_info,
            prompt_context=prompt_context,
            prior=base.style,
        )

        memory = ProjectMemory(
            project_id=resolved_id,
            topic=research.topic,
            characters=characters,
            world=world,
            style=style,
            registry=registry,
        )

        if persist:
            try:
                self._store.save(memory)
            except Exception as exc:  # noqa: BLE001 - optional persistence
                logger.warning(
                    "event=world_builder_persist_skipped project_id=%r error=%s",
                    resolved_id,
                    exc,
                )

        logger.info(
            "event=world_builder_complete project_id=%r characters=%s "
            "locations=%s style=%r",
            memory.project_id,
            len(memory.characters),
            len(memory.world.locations),
            memory.style.visual_style[:60] if memory.style.visual_style else "",
        )
        return memory

    def _build_characters(
        self,
        research: ResearchResult,
        registry: AssetRegistry,
        *,
        prior: list[CharacterBible],
    ) -> list[CharacterBible]:
        by_id = {character.id: character for character in prior}
        clothing = _clothing_primary(research)
        weapons = list(research.weapons[:3])
        results: list[CharacterBible] = []
        seen: set[str] = set()

        for raw in research.key_people:
            name = " ".join(str(raw).split())
            if not name:
                continue
            char_id = slugify(name, fallback="character")
            if char_id in seen:
                continue
            seen.add(char_id)

            record = registry.register(
                kind=AssetKind.CHARACTER,
                slug=char_id,
                label=name,
                metadata={"source": "research.key_people"},
            )
            existing = by_id.get(char_id)
            if existing is not None:
                appearance = existing.appearance
                if clothing and not appearance.uniform.primary:
                    appearance = appearance.model_copy(
                        update={
                            "uniform": appearance.uniform.model_copy(
                                update={"primary": clothing}
                            )
                        }
                    )
                if weapons and not appearance.weapons:
                    appearance = appearance.model_copy(update={"weapons": weapons})
                results.append(
                    existing.model_copy(
                        update={
                            "asset_id": record.id,
                            "name": name,
                            "appearance": appearance,
                        }
                    )
                )
                continue

            era_note = research.time_period or ""
            body = "period-accurate figure"
            if era_note:
                body = f"period-accurate figure, era {era_note}"
            results.append(
                CharacterBible(
                    id=char_id,
                    asset_id=record.id,
                    name=name,
                    appearance=AppearanceBible(
                        body=body,
                        uniform=UniformBible(primary=clothing),
                        weapons=weapons,
                    ),
                    role="key_person",
                    negative=["modern clothing", "anachronistic accessories"],
                    notes=(
                        f"consistent likeness of {name} across all scenes"
                        + (f", era {era_note}" if era_note else "")
                    ),
                )
            )
        return results

    def _build_world(
        self,
        research: ResearchResult,
        registry: AssetRegistry,
        *,
        prior: WorldBible,
    ) -> WorldBible:
        by_id = {location.id: location for location in prior.locations}
        locations: list[LocationBible] = []
        seen: set[str] = set()
        architecture = _architecture_text(research)
        names: list[str] = []
        if research.location:
            names.append(research.location)
        names.extend(research.key_locations)
        for detail in research.visual_details[:2]:
            # Prefer explicit places; skip generic visual notes when we already
            # have named locations.
            if names:
                break
            if detail:
                names.append(detail)

        for raw in names:
            name = " ".join(str(raw).split())
            if not name:
                continue
            loc_id = slugify(name, fallback="location")
            if loc_id in seen:
                continue
            seen.add(loc_id)
            record = registry.register(
                kind=AssetKind.LOCATION,
                slug=loc_id,
                label=name,
                metadata={"source": "research.locations"},
            )
            existing = by_id.get(loc_id)
            if existing is not None:
                locations.append(
                    existing.model_copy(
                        update={
                            "asset_id": record.id,
                            "name": name,
                            "architecture": existing.architecture or architecture,
                            "time": existing.time or research.time_period,
                        }
                    )
                )
                continue
            locations.append(
                LocationBible(
                    id=loc_id,
                    asset_id=record.id,
                    name=name,
                    architecture=architecture,
                    time=research.time_period,
                    style="cinematic realism",
                    notes=", ".join(research.visual_details[:3]),
                )
            )

        primary_id = ""
        if locations:
            primary_id = locations[0].id
        elif prior.primary_location_id:
            primary_id = prior.primary_location_id

        return WorldBible(
            locations=locations or list(prior.locations),
            primary_location_id=primary_id,
            era=research.time_period or prior.era,
            season=prior.season,
            notes=prior.notes,
        )

    def _build_style(
        self,
        research: ResearchResult,
        registry: AssetRegistry,
        *,
        domain_info: DomainInfo | None,
        prompt_context: DomainPromptContext | None,
        prior: StyleBible,
    ) -> StyleBible:
        record = registry.register(
            kind=AssetKind.STYLE,
            slug="project_style",
            label="Project Style",
            metadata={"source": "style_bible"},
        )

        visual_style = prior.visual_style
        camera = prior.camera
        lighting = prior.lighting
        color_palette = prior.color_palette
        quality = prior.quality
        lens = prior.lens

        if prompt_context is not None:
            visual_style = visual_style or prompt_context.style
            camera = camera or prompt_context.camera
            lighting = lighting or prompt_context.lighting
            color_palette = color_palette or prompt_context.color_palette
            if prompt_context.quality_tags and not quality:
                quality = ", ".join(prompt_context.quality_tags)
        if domain_info is not None:
            visual_style = visual_style or domain_info.suggested_style
            camera = camera or domain_info.suggested_camera
        if not visual_style:
            visual_style = "cinematic realism"
        if research.time_period and "period" not in visual_style.casefold():
            # Soft era cue without overriding an explicit style identity.
            if prior.visual_style:
                pass
            else:
                visual_style = f"{visual_style}, period accurate"

        return StyleBible(
            id="project_style",
            asset_id=record.id,
            visual_style=visual_style,
            camera=camera,
            lighting=lighting,
            color_palette=color_palette,
            quality=quality or "highly detailed, sharp focus",
            lens=lens,
        )
