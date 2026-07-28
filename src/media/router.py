"""Abstract media router — modality engines subclass this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.media.request import MediaRequest


class MediaRouter(ABC):
    """Shared entry-point shape for image / video / future media engines.

    Subclasses expose a typed ``generate`` that accepts either a modality
    request model or convenience kwargs, but all resolve through a single
    public method so the pipeline never binds to a backend.
    """

    @abstractmethod
    def generate(self, request: MediaRequest | str, **kwargs: Any) -> Any:
        """Generate media for ``request`` (or a prompt string + kwargs)."""
