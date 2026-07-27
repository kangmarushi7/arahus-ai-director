"""SQLAlchemy 2.0 ORM models for AI Director.

Hierarchy::

    Project (1) ──< Scene (1) ──< PromptVersion (1) ──< Image
                      │
                      └──< SceneCharacter >── Character
                                                ├──< CharacterAlias
                                                └──< CharacterReferenceImage

Primary keys are UUIDs. Status columns use Python/SQL enums. Child rows
cascade-delete with their parents.

Import from this package (``from src.database.models import Project``) so all
mappers are registered on :class:`~src.database.base.Base`.
"""

from __future__ import annotations

from src.database.base import Base
from src.database.models.character import Character
from src.database.models.character_alias import CharacterAlias
from src.database.models.character_reference_image import CharacterReferenceImage
from src.database.models.image import Image, ImageStatus
from src.database.models.project import Project, ProjectStatus
from src.database.models.prompt_version import PromptVersion, PromptVersionStatus
from src.database.models.scene import Scene, SceneStatus
from src.database.models.scene_character import SceneCharacter

__all__ = [
    "Base",
    "Character",
    "CharacterAlias",
    "CharacterReferenceImage",
    "Image",
    "ImageStatus",
    "Project",
    "ProjectStatus",
    "PromptVersion",
    "PromptVersionStatus",
    "Scene",
    "SceneCharacter",
    "SceneStatus",
]
