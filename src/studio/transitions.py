"""Scene lifecycle state machine for Storyboard Studio."""

from __future__ import annotations

from src.studio.models import SceneLifecycle

# Forward-only happy path. Regeneration helpers may jump backward explicitly.
ALLOWED_TRANSITIONS: dict[SceneLifecycle, frozenset[SceneLifecycle]] = {
    SceneLifecycle.DRAFT: frozenset({SceneLifecycle.APPROVED}),
    SceneLifecycle.APPROVED: frozenset({SceneLifecycle.IMAGE_GENERATED}),
    SceneLifecycle.IMAGE_GENERATED: frozenset({SceneLifecycle.IMAGE_APPROVED}),
    SceneLifecycle.IMAGE_APPROVED: frozenset({SceneLifecycle.VIDEO_GENERATED}),
    SceneLifecycle.VIDEO_GENERATED: frozenset({SceneLifecycle.VIDEO_APPROVED}),
    SceneLifecycle.VIDEO_APPROVED: frozenset({SceneLifecycle.LOCKED}),
    SceneLifecycle.LOCKED: frozenset(),
}

# Explicit regeneration rollbacks (target status after invalidate).
REGENERATION_ROLLBACK: dict[str, SceneLifecycle] = {
    "camera": SceneLifecycle.DRAFT,
    "prompt": SceneLifecycle.DRAFT,
    "scene": SceneLifecycle.DRAFT,
    "image": SceneLifecycle.APPROVED,
    "video": SceneLifecycle.IMAGE_APPROVED,
}


class TransitionError(ValueError):
    """Raised when a lifecycle transition is not allowed."""

    def __init__(
        self,
        message: str,
        *,
        current: SceneLifecycle | None = None,
        target: SceneLifecycle | None = None,
    ) -> None:
        super().__init__(message)
        self.current = current
        self.target = target


def can_transition(current: SceneLifecycle, target: SceneLifecycle) -> bool:
    """Return True when ``current → target`` is a legal forward transition."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: SceneLifecycle, target: SceneLifecycle) -> None:
    """Raise :class:`TransitionError` if the transition is illegal."""
    if can_transition(current, target):
        return
    allowed = ", ".join(sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset())))
    raise TransitionError(
        f"Cannot transition scene from {current.value!r} to {target.value!r}"
        + (f"; allowed: {allowed or '(none)'}" if current != target else ""),
        current=current,
        target=target,
    )


def next_status(current: SceneLifecycle) -> SceneLifecycle | None:
    """Return the single next happy-path status, if any."""
    options = ALLOWED_TRANSITIONS.get(current, frozenset())
    if len(options) != 1:
        return None
    return next(iter(options))


def rollback_for(target: str) -> SceneLifecycle:
    """Return the lifecycle status after a regenerate-``target`` action."""
    key = target.strip().lower()
    try:
        return REGENERATION_ROLLBACK[key]
    except KeyError as exc:
        known = ", ".join(sorted(REGENERATION_ROLLBACK))
        raise TransitionError(
            f"Unknown regenerate target {target!r}; expected one of {known}"
        ) from exc
