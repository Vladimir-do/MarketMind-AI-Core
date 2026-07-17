"""add import mapping presets

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "import_mapping_presets",
        sa.Column("preset_id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="local-import-v1"),
        sa.Column("source_columns_json", sa.Text(), nullable=False),
        sa.Column("mapping_json", sa.Text(), nullable=False),
        sa.Column("header_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime()),
    )
    op.create_index(
        "ix_import_mapping_presets_project_active",
        "import_mapping_presets",
        ["project_id", "active"],
    )
    op.create_index(
        "ix_import_mapping_presets_project_fingerprint",
        "import_mapping_presets",
        ["project_id", "header_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_mapping_presets_project_fingerprint", table_name="import_mapping_presets")
    op.drop_index("ix_import_mapping_presets_project_active", table_name="import_mapping_presets")
    op.drop_table("import_mapping_presets")
