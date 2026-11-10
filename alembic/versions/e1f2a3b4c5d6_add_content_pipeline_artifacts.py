"""add content pipeline artifacts

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-08-02 00:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_pipeline_artifacts",
        sa.Column("artifact_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_product_id",
            sa.String(length=64),
            sa.ForeignKey("project_products.project_product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("model_used", sa.String(length=64), nullable=True),
        sa.Column(
            "job_id", sa.String(length=64), sa.ForeignKey("job_records.job_id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_cpa_project_product_type_version",
        "content_pipeline_artifacts",
        ["project_id", "project_product_id", "artifact_type", "version_number"],
        unique=True,
    )
    op.create_index(
        "ix_cpa_product_type_created",
        "content_pipeline_artifacts",
        ["product_id", "artifact_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cpa_product_type_created", table_name="content_pipeline_artifacts")
    op.drop_index("ix_cpa_project_product_type_version", table_name="content_pipeline_artifacts")
    op.drop_table("content_pipeline_artifacts")
