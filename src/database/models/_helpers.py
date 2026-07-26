"""Shared helpers for ORM model modules."""

from __future__ import annotations

import enum


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Persist enum *values* (not names) in PostgreSQL."""
    return [member.value for member in enum_cls]
