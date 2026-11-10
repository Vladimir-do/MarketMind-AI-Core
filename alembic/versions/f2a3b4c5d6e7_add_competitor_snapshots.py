"""add competitor snapshots

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-02 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitor_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
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
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("competitor_name", sa.Text(), nullable=False),
        sa.Column("competitor_url", sa.Text(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("old_price", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("reviews_count", sa.Integer(), nullable=True),
        sa.Column("reviews_json", sa.Text(), nullable=True),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_competitor_snapshots_batch", "competitor_snapshots", ["batch_id"])
    op.create_index(
        "ix_competitor_snapshots_project_product_created",
        "competitor_snapshots",
        ["project_id", "project_product_id", "created_at"],
    )
    op.create_index("ix_competitor_snapshots_product_id", "competitor_snapshots", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_competitor_snapshots_product_id", table_name="competitor_snapshots")
    op.drop_index("ix_competitor_snapshots_project_product_created", table_name="competitor_snapshots")
    op.drop_index("ix_competitor_snapshots_batch", table_name="competitor_snapshots")
    op.drop_table("competitor_snapshots")
