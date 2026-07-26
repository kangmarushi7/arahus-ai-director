"""In-process event bus for loose coupling between pipeline stages.

Agents and services publish typed dataclass events; subscribers receive them
without depending on each other directly. The bus is process-local and
thread-safe, and uses only the Python standard library.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

E = TypeVar("E", bound="Event")
EventHandler = Callable[[Any], None]


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Event:
    """Base type for every bus event."""

    topic: str
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class ResearchCompleted(Event):
    """Emitted after the research agent returns a validated result."""

    time_period: str = ""
    location: str = ""


@dataclass(frozen=True)
class DirectorCompleted(Event):
    """Emitted after the director agent returns a scene plan."""

    scene_count: int = 0


@dataclass(frozen=True)
class PromptCompleted(Event):
    """Emitted after the prompt agent returns a storyboard of image prompts."""

    scene_count: int = 0


@dataclass(frozen=True)
class ReviewCompleted(Event):
    """Emitted after the review agent scores a storyboard."""

    overall_score: float = 0.0
    approved: bool = False


@dataclass(frozen=True)
class ImageGenerated(Event):
    """Emitted after one scene image has been generated."""

    scene_id: int = 0
    prompt: str = ""
    url: str | None = None


@dataclass(frozen=True)
class VideoGenerated(Event):
    """Emitted after a video has been produced from storyboard images."""

    url: str | None = None
    duration_seconds: float | None = None


class EventBus:
    """Thread-safe publish/subscribe bus for typed pipeline events.

    Subscribers register against a concrete event class. Publishing an event
    instance delivers it to every matching subscriber. Handler exceptions are
    isolated so one failing listener cannot block the others.
    """

    def __init__(self) -> None:
        """Create an empty subscriber registry."""
        self._lock = threading.RLock()
        self._subscribers: dict[type[Event], list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Register ``handler`` for events of ``event_type``.

        Args:
            event_type: Dataclass event class to listen for.
            handler: Callable invoked with each published event instance.

        Raises:
            TypeError: If ``event_type`` is not a subclass of :class:`Event`.
            ValueError: If ``handler`` is already subscribed for that type.
        """
        if not isinstance(event_type, type) or not issubclass(event_type, Event):
            raise TypeError("event_type must be a subclass of Event")

        with self._lock:
            handlers = self._subscribers[event_type]
            if handler in handlers:
                raise ValueError(
                    f"handler is already subscribed to {event_type.__name__}"
                )
            handlers.append(handler)  # type: ignore[arg-type]

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Remove ``handler`` for ``event_type``.

        Args:
            event_type: Event class the handler was registered against.
            handler: Previously subscribed callable.

        Raises:
            TypeError: If ``event_type`` is not a subclass of :class:`Event`.
            ValueError: If ``handler`` is not currently subscribed.
        """
        if not isinstance(event_type, type) or not issubclass(event_type, Event):
            raise TypeError("event_type must be a subclass of Event")

        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            try:
                handlers.remove(handler)  # type: ignore[arg-type]
            except ValueError as exc:
                raise ValueError(
                    f"handler is not subscribed to {event_type.__name__}"
                ) from exc
            if not handlers and event_type in self._subscribers:
                del self._subscribers[event_type]

    def publish(self, event: Event) -> None:
        """Deliver ``event`` to every subscriber of its concrete type.

        Args:
            event: Event instance to broadcast.

        Raises:
            TypeError: If ``event`` is not an :class:`Event` instance.
        """
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")

        with self._lock:
            handlers = list(self._subscribers.get(type(event), ()))

        errors: list[BaseException] = []
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - isolate subscriber failures
                errors.append(exc)

        if errors:
            details = "; ".join(f"{type(error).__name__}: {error}" for error in errors)
            raise RuntimeError(
                f"One or more subscribers failed for {type(event).__name__}: {details}"
            )

    def clear(self) -> None:
        """Remove every subscriber from the bus."""
        with self._lock:
            self._subscribers.clear()

    def subscriber_count(self, event_type: type[Event] | None = None) -> int:
        """Return the number of subscribers, optionally for one event type."""
        with self._lock:
            if event_type is None:
                return sum(len(handlers) for handlers in self._subscribers.values())
            return len(self._subscribers.get(event_type, ()))
