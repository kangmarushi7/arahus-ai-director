"""Create core schema tables and enums.

Revision ID: a1b2c3d4e5f6
Revises: 33c6ba86f565
Create Date: 2026-07-28 00:08:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "33c6ba86f565"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

project_status = postgresql.ENUM(
    "created",
    "running",
    "playground",
    "completed",
    "failed",
    "archived",
    name="project_status",
    create_type=False,
)
scene_status = postgresql.ENUM(
    "draft",
    "ready",
    "rendering",
    "completed",
    "failed",
    name="scene_status",
    create_type=False,
)
prompt_version_status = postgresql.ENUM(
    "draft",
    "active",
    "superseded",
    "rejected",
    name="prompt_version_status",
    create_type=False,
)
image_status = postgresql.ENUM(
    "pending",
    "processing",
    "ok",
    "generated_no_url",
    "failed",
    name="image_status",
    create_type=False,
)


def upgrade() -> None:
    """Create PostgreSQL enums and all core ORM tables."""
    bind = op.get_bind()
    postgresql.ENUM(
        "created",
        "running",
        "playground",
        "completed",
        "failed",
        "archived",
        name="project_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "draft",
        "ready",
        "rendering",
        "completed",
        "failed",
        name="scene_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "draft",
        "active",
        "superseded",
        "rejected",
        name="prompt_version_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "pending",
        "processing",
        "ok",
        "generated_no_url",
        "failed",
        name="image_status",
    ).create(bind, checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            project_status,
            server_default="created",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_topic", "projects", ["topic"], unique=False)
    op.create_index("ix_projects_status", "projects", ["status"], unique=False)
    op.create_index("ix_projects_created_at", "projects", ["created_at"], unique=False)
    op.create_index(
        "ix_projects_status_created_at",
        "projects",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "characters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("appearance", sa.Text(), nullable=False),
        sa.Column("era", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=256), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_characters_name", "characters", ["name"], unique=True)
    op.create_index("ix_characters_era", "characters", ["era"], unique=False)
    op.create_index(
        "ix_characters_created_at",
        "characters",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_characters_name_created_at",
        "characters",
        ["name", "created_at"],
        unique=False,
    )

    op.create_table(
        "scenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("scene_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            scene_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "scene_number",
            name="uq_scenes_project_number",
        ),
    )
    op.create_index("ix_scenes_project_id", "scenes", ["project_id"], unique=False)
    op.create_index("ix_scenes_status", "scenes", ["status"], unique=False)
    op.create_index(
        "ix_scenes_project_status",
        "scenes",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column(
            "model",
            sa.String(length=256),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "status",
            prompt_version_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "is_selected",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["scenes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scene_id",
            "version",
            name="uq_prompt_versions_scene_version",
        ),
    )
    op.create_index(
        "ix_prompt_versions_scene_id",
        "prompt_versions",
        ["scene_id"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_versions_model",
        "prompt_versions",
        ["model"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_versions_status",
        "prompt_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_versions_created_at",
        "prompt_versions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_versions_scene_selected",
        "prompt_versions",
        ["scene_id", "is_selected"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_versions_scene_status",
        "prompt_versions",
        ["scene_id", "status"],
        unique=False,
    )

    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column(
            "status",
            image_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_images_prompt_version_id",
        "images",
        ["prompt_version_id"],
        unique=False,
    )
    op.create_index("ix_images_status", "images", ["status"], unique=False)
    op.create_index("ix_images_created_at", "images", ["created_at"], unique=False)
    op.create_index(
        "ix_images_prompt_status",
        "images",
        ["prompt_version_id", "status"],
        unique=False,
    )

    op.create_table(
        "character_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias", name="uq_character_aliases_alias"),
    )
    op.create_index(
        "ix_character_aliases_character_id",
        "character_aliases",
        ["character_id"],
        unique=False,
    )
    op.create_index(
        "ix_character_aliases_alias",
        "character_aliases",
        ["alias"],
        unique=False,
    )

    op.create_table(
        "character_reference_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_character_reference_images_character_id",
        "character_reference_images",
        ["character_id"],
        unique=False,
    )
    op.create_index(
        "ix_character_reference_images_character_primary",
        "character_reference_images",
        ["character_id", "is_primary"],
        unique=False,
    )

    op.create_table(
        "scene_characters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("role_in_scene", sa.String(length=256), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_featured",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["scenes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scene_id",
            "character_id",
            name="uq_scene_characters_scene_character",
        ),
    )
    op.create_index(
        "ix_scene_characters_scene_id",
        "scene_characters",
        ["scene_id"],
        unique=False,
    )
    op.create_index(
        "ix_scene_characters_character_id",
        "scene_characters",
        ["character_id"],
        unique=False,
    )
    op.create_index(
        "ix_scene_characters_scene_sort",
        "scene_characters",
        ["scene_id", "sort_order"],
        unique=False,
    )


def downgrade() -> None:
    """Drop core tables, then PostgreSQL enums."""
    op.drop_table("scene_characters")
    op.drop_table("character_reference_images")
    op.drop_table("character_aliases")
    op.drop_table("images")
    op.drop_table("prompt_versions")
    op.drop_table("scenes")
    op.drop_table("characters")
    op.drop_table("projects")

    bind = op.get_bind()
    image_status.drop(bind, checkfirst=True)
    prompt_version_status.drop(bind, checkfirst=True)
    scene_status.drop(bind, checkfirst=True)
    project_status.drop(bind, checkfirst=True)
