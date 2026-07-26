"""Baseline Alembic revision (no schema changes).

Revision ID: 33c6ba86f565
Revises:
Create Date: 2026-07-27 00:21:49.779834

Tables are intentionally not created here. Add ORM models in
``src/database/models.py``, then generate revisions with::

    python -m scripts.db revision -m \"describe change\" --autogenerate
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "33c6ba86f565"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op baseline — schema migrations start in later revisions."""
    pass


def downgrade() -> None:
    """No-op baseline."""
    pass
