"""Character & World Memory — persistent project identity for visual consistency."""

from __future__ import annotations

from src.memory.builder import WorldBuilder
from src.memory.ids import project_id_for_topic, slugify
from src.memory.packs import (
    CharacterBiblePack,
    ContinuityPack,
    StyleBiblePack,
    WorldBiblePack,
    build_memory_packs,
    composer_with_memory,
)
from src.memory.store import ProjectMemoryStore
from src.models.memory import (
    AppearanceBible,
    AssetKind,
    AssetRecord,
    AssetRegistry,
    CharacterBible,
    FaceBible,
    HairBible,
    LocationBible,
    ProjectMemory,
    SceneContinuityMeta,
    StyleBible,
    UniformBible,
    WorldBible,
)

__all__ = [
    "AppearanceBible",
    "AssetKind",
    "AssetRecord",
    "AssetRegistry",
    "CharacterBible",
    "CharacterBiblePack",
    "ContinuityPack",
    "FaceBible",
    "HairBible",
    "LocationBible",
    "ProjectMemory",
    "ProjectMemoryStore",
    "SceneContinuityMeta",
    "StyleBible",
    "StyleBiblePack",
    "UniformBible",
    "WorldBible",
    "WorldBiblePack",
    "WorldBuilder",
    "build_memory_packs",
    "composer_with_memory",
    "project_id_for_topic",
    "slugify",
]
