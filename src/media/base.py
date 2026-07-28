"""Shared media kinds and provider protocol."""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MediaKind(str, Enum):
    """Modality handled by a media engine."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    MESH_3D = "mesh_3d"


@runtime_checkable
class MediaProvider(Protocol):
    """Provider-agnostic media generation surface.

    Image and video providers implement their own ``generate`` signatures while
    advertising a stable ``name`` and ``kind``. Future audio / 3D / voice
    providers reuse the same identity contract.
    """

    @property
    def name(self) -> str:
        """Stable provider identifier (e.g. ``runpod``)."""

    @property
    def kind(self) -> MediaKind:
        """Modality this provider produces."""

    def healthcheck(self) -> dict[str, Any]:
        """Optional readiness probe; default implementations may return ``{}``."""
