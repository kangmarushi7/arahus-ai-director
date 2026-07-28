"""Character, world, and style memory models for long-term visual consistency."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import StrictModel


def _normalize_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _normalize_str_list(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    if isinstance(value, (list, tuple)):
        return [" ".join(str(item).split()) for item in value if str(item).strip()]
    return value


class AssetKind(str, Enum):
    """Kinds of reusable creative assets with stable IDs."""

    CHARACTER = "character"
    LOCATION = "location"
    STYLE = "style"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"


class AssetRecord(StrictModel):
    """One registered project asset (Character #17, Location #3, …)."""

    id: int = Field(ge=1)
    kind: AssetKind
    slug: str
    label: str
    refs: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug", "label", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


class AssetRegistry(StrictModel):
    """Stable numeric IDs for characters, locations, style, and media."""

    project_id: str
    next_id: int = Field(default=1, ge=1)
    assets: dict[str, AssetRecord] = Field(default_factory=dict)

    @field_validator("project_id", mode="before")
    @classmethod
    def _normalize_project_id(cls, value: object) -> object:
        return _normalize_text(value)

    def get_by_id(self, asset_id: int) -> AssetRecord | None:
        for record in self.assets.values():
            if record.id == asset_id:
                return record
        return None

    def get_by_slug(self, slug: str) -> AssetRecord | None:
        key = " ".join(slug.split()).casefold()
        for record in self.assets.values():
            if record.slug.casefold() == key:
                return record
        return self.assets.get(slug)

    def register(
        self,
        *,
        kind: AssetKind,
        slug: str,
        label: str,
        refs: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRecord:
        """Return existing asset for ``slug`` or allocate the next stable ID."""
        cleaned_slug = " ".join(slug.split())
        if not cleaned_slug:
            raise ValueError("slug must be a non-empty string")
        existing = self.get_by_slug(cleaned_slug)
        if existing is not None:
            if kind != existing.kind:
                raise ValueError(
                    f"Asset slug {cleaned_slug!r} already registered as "
                    f"{existing.kind.value}, not {kind.value}"
                )
            updates: dict[str, Any] = {"label": " ".join(label.split()) or existing.label}
            if refs:
                updates["refs"] = {**existing.refs, **refs}
            if metadata:
                updates["metadata"] = {**existing.metadata, **metadata}
            updated = existing.model_copy(update=updates)
            self.assets[cleaned_slug] = updated
            return updated

        asset_id = self.next_id
        self.next_id = asset_id + 1
        record = AssetRecord(
            id=asset_id,
            kind=kind,
            slug=cleaned_slug,
            label=" ".join(label.split()) or cleaned_slug,
            refs=dict(refs or {}),
            metadata=dict(metadata or {}),
        )
        self.assets[cleaned_slug] = record
        return record

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class FaceBible(StrictModel):
    """Facial identity anchors for a character."""

    jaw: str = ""
    nose: str = ""
    eyes: str = ""

    @field_validator("jaw", "nose", "eyes", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


class HairBible(StrictModel):
    """Hair style / color anchors."""

    style: str = ""
    color: str = ""

    @field_validator("style", "color", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)


class UniformBible(StrictModel):
    """Costume / wardrobe anchors."""

    primary: str = ""
    hat: str = ""
    accessories: list[str] = Field(default_factory=list)

    @field_validator("primary", "hat", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("accessories", mode="before")
    @classmethod
    def _normalize_accessories(cls, value: object) -> object:
        return _normalize_str_list(value)


class AppearanceBible(StrictModel):
    """Structured visual identity for a character."""

    age: str = ""
    height: str = ""
    body: str = ""
    face: FaceBible = Field(default_factory=FaceBible)
    hair: HairBible = Field(default_factory=HairBible)
    uniform: UniformBible = Field(default_factory=UniformBible)
    horse: str = ""
    weapons: list[str] = Field(default_factory=list)

    @field_validator("age", "height", "body", "horse", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("weapons", mode="before")
    @classmethod
    def _normalize_weapons(cls, value: object) -> object:
        return _normalize_str_list(value)

    def to_prompt_fragment(self) -> str:
        """Flatten appearance into a composer-ready fragment."""
        parts: list[str] = []
        if self.age:
            parts.append(f"age {self.age}")
        if self.height:
            parts.append(self.height)
        if self.body:
            parts.append(self.body)
        face_bits = [
            bit
            for bit in (
                f"{self.face.jaw} jaw" if self.face.jaw else "",
                f"{self.face.nose} nose" if self.face.nose else "",
                f"{self.face.eyes} eyes" if self.face.eyes else "",
            )
            if bit
        ]
        if face_bits:
            parts.append(", ".join(face_bits))
        hair_bits = [bit for bit in (self.hair.color, self.hair.style) if bit]
        if hair_bits:
            parts.append(" ".join(hair_bits) + " hair")
        if self.uniform.primary:
            parts.append(self.uniform.primary)
        if self.uniform.hat:
            parts.append(self.uniform.hat)
        parts.extend(self.uniform.accessories)
        if self.horse:
            parts.append(f"horse: {self.horse}")
        parts.extend(self.weapons)
        return ", ".join(parts)


class CharacterBible(StrictModel):
    """Persistent character identity for a project."""

    id: str
    asset_id: int = Field(ge=1)
    name: str
    appearance: AppearanceBible = Field(default_factory=AppearanceBible)
    personality: str = ""
    voice: str = ""
    negative: list[str] = Field(default_factory=list)
    role: str = ""
    notes: str = ""

    @field_validator("id", "name", "personality", "voice", "role", "notes", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @field_validator("negative", mode="before")
    @classmethod
    def _normalize_negative(cls, value: object) -> object:
        return _normalize_str_list(value)

    def to_prompt_fragment(self) -> str:
        """Render identity for PromptComposer injection."""
        parts = [f"{self.name} (Character #{self.asset_id})"]
        appearance = self.appearance.to_prompt_fragment()
        if appearance:
            parts.append(appearance)
        if self.personality:
            parts.append(f"personality {self.personality}")
        if self.voice:
            parts.append(f"voice {self.voice}")
        return ", ".join(parts)

    def to_bible_line(self) -> str:
        """Compact line for legacy character_bible string prompts."""
        appearance = self.appearance.to_prompt_fragment() or "consistent likeness"
        return f"- {self.name} [#{self.asset_id}]: {appearance}"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class LocationBible(StrictModel):
    """Persistent location / set identity for a project."""

    id: str
    asset_id: int = Field(ge=1)
    name: str
    weather: str = ""
    architecture: str = ""
    time: str = ""
    lighting: str = ""
    crowd: str = ""
    style: str = ""
    notes: str = ""

    @field_validator(
        "id",
        "name",
        "weather",
        "architecture",
        "time",
        "lighting",
        "crowd",
        "style",
        "notes",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    def to_prompt_fragment(self) -> str:
        parts = [f"{self.name} (Location #{self.asset_id})"]
        for label, value in (
            ("weather", self.weather),
            ("architecture", self.architecture),
            ("time", self.time),
            ("lighting", self.lighting),
            ("crowd", self.crowd),
            ("style", self.style),
        ):
            if value:
                parts.append(f"{label}: {value}")
        if self.notes:
            parts.append(self.notes)
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class WorldBible(StrictModel):
    """Project world memory: locations and shared environmental anchors."""

    locations: list[LocationBible] = Field(default_factory=list)
    primary_location_id: str = ""
    season: str = ""
    era: str = ""
    notes: str = ""

    @field_validator("primary_location_id", "season", "era", "notes", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    def primary_location(self) -> LocationBible | None:
        if self.primary_location_id:
            for location in self.locations:
                if location.id == self.primary_location_id:
                    return location
        return self.locations[0] if self.locations else None

    def to_prompt_fragment(self) -> str:
        parts: list[str] = []
        if self.era:
            parts.append(f"era {self.era}")
        if self.season:
            parts.append(f"season {self.season}")
        primary = self.primary_location()
        if primary is not None:
            parts.append(primary.to_prompt_fragment())
        elif self.locations:
            parts.append(self.locations[0].to_prompt_fragment())
        if self.notes:
            parts.append(self.notes)
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class StyleBible(StrictModel):
    """Project-wide visual identity shared by every image/video."""

    id: str = "project_style"
    asset_id: int | None = Field(default=None, ge=1)
    visual_style: str = ""
    camera: str = ""
    lighting: str = ""
    color_palette: str = ""
    quality: str = ""
    lens: str = ""

    @field_validator(
        "id",
        "visual_style",
        "camera",
        "lighting",
        "color_palette",
        "quality",
        "lens",
        mode="before",
    )
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    def to_prompt_fragment(self) -> str:
        parts = [
            part
            for part in (
                self.visual_style,
                self.camera,
                self.lens,
                self.lighting,
                self.color_palette,
                self.quality,
            )
            if part.strip()
        ]
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SceneContinuityMeta(StrictModel):
    """Structured continuity directives between scenes."""

    previous_scene: str = ""
    keep: list[str] = Field(default_factory=list)
    change: list[str] = Field(default_factory=list)

    @field_validator("previous_scene", mode="before")
    @classmethod
    def _normalize_previous(cls, value: object) -> object:
        if isinstance(value, int):
            return f"scene_{value}"
        return _normalize_text(value)

    @field_validator("keep", "change", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_str_list(value)

    def to_prompt_fragment(self) -> str:
        parts: list[str] = []
        if self.previous_scene:
            parts.append(f"continues from {self.previous_scene}")
        if self.keep:
            parts.append("keep " + ", ".join(self.keep))
        if self.change:
            parts.append("change " + ", ".join(self.change))
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ProjectMemory(StrictModel):
    """Full persistent memory for one creative project."""

    project_id: str
    topic: str = ""
    characters: list[CharacterBible] = Field(default_factory=list)
    world: WorldBible = Field(default_factory=WorldBible)
    style: StyleBible = Field(default_factory=StyleBible)
    registry: AssetRegistry | None = None

    @field_validator("project_id", "topic", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        return _normalize_text(value)

    @model_validator(mode="after")
    def _ensure_registry(self) -> ProjectMemory:
        if self.registry is None:
            self.registry = AssetRegistry(project_id=self.project_id)
        elif self.registry.project_id != self.project_id:
            self.registry = self.registry.model_copy(
                update={"project_id": self.project_id}
            )
        return self

    def character_bible_text(self) -> str:
        """Legacy multi-line bible string for director / prompt LLM paths."""
        if not self.characters:
            return ""
        lines = [
            "Character bible (keep visual identity consistent across scenes):",
            *[character.to_bible_line() for character in self.characters],
        ]
        return "\n".join(lines)

    def find_character(self, name_or_id: str) -> CharacterBible | None:
        key = " ".join(name_or_id.split()).casefold()
        for character in self.characters:
            if character.id.casefold() == key or character.name.casefold() == key:
                return character
        return None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMemory:
        return cls.model_validate(data)
