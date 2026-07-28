"""Create pipeline_runs / pipeline_log_entries audit tables.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28 21:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit tables and enums."""
    bind = op.get_bind()
    postgresql.ENUM(
        "running",
        "completed",
        "failed",
        name="pipeline_run_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "llm",
        "image",
        "video",
        "stage",
        name="pipeline_log_kind",
    ).create(bind, checkfirst=True)

    pipeline_run_status = postgresql.ENUM(
        "running",
        "completed",
        "failed",
        name="pipeline_run_status",
        create_type=False,
    )
    pipeline_log_kind = postgresql.ENUM(
        "llm",
        "image",
        "video",
        "stage",
        name="pipeline_log_kind",
        create_type=False,
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            pipeline_run_status,
            server_default="running",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_topic", "pipeline_runs", ["topic"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])
    op.create_index("ix_pipeline_runs_started_at", "pipeline_runs", ["started_at"])
    op.create_index(
        "ix_pipeline_runs_status_started_at",
        "pipeline_runs",
        ["status", "started_at"],
    )

    op.create_table(
        "pipeline_log_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("kind", pipeline_log_kind, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_log_entries_run_id",
        "pipeline_log_entries",
        ["run_id"],
    )
    op.create_index("ix_pipeline_log_entries_tag", "pipeline_log_entries", ["tag"])
    op.create_index("ix_pipeline_log_entries_kind", "pipeline_log_entries", ["kind"])
    op.create_index(
        "ix_pipeline_log_entries_created_at",
        "pipeline_log_entries",
        ["created_at"],
    )
    op.create_index(
        "ix_pipeline_log_entries_run_tag",
        "pipeline_log_entries",
        ["run_id", "tag"],
    )
    op.create_index(
        "ix_pipeline_log_entries_run_kind",
        "pipeline_log_entries",
        ["run_id", "kind"],
    )


def downgrade() -> None:
    """Drop audit tables and enums."""
    op.drop_index(
        "ix_pipeline_log_entries_run_kind",
        table_name="pipeline_log_entries",
    )
    op.drop_index(
        "ix_pipeline_log_entries_run_tag",
        table_name="pipeline_log_entries",
    )
    op.drop_index(
        "ix_pipeline_log_entries_created_at",
        table_name="pipeline_log_entries",
    )
    op.drop_index("ix_pipeline_log_entries_kind", table_name="pipeline_log_entries")
    op.drop_index("ix_pipeline_log_entries_tag", table_name="pipeline_log_entries")
    op.drop_index("ix_pipeline_log_entries_run_id", table_name="pipeline_log_entries")
    op.drop_table("pipeline_log_entries")

    op.drop_index(
        "ix_pipeline_runs_status_started_at",
        table_name="pipeline_runs",
    )
    op.drop_index("ix_pipeline_runs_started_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_topic", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    bind = op.get_bind()
    postgresql.ENUM(name="pipeline_log_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="pipeline_run_status").drop(bind, checkfirst=True)
