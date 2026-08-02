"""add card editor tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 12:45:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_card_drafts",
        sa.Column("draft_id", sa.String(length=64), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_version_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_product_card_drafts_product_status_updated",
        "product_card_drafts",
        ["product_id", "status", "updated_at"],
    )
    op.create_index("ix_product_card_drafts_product_id", "product_card_drafts", ["product_id"])

    op.create_table(
        "product_card_versions",
        sa.Column("version_id", sa.String(length=128), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("base_version_id", sa.String(length=128), nullable=True),
        sa.Column("trigger_event_id", sa.String(length=128), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_product_card_versions_product_number",
        "product_card_versions",
        ["product_id", "version_number"],
        unique=True,
    )
    op.create_index(
        "ix_product_card_versions_product_created",
        "product_card_versions",
        ["product_id", "created_at"],
    )
    op.create_index("ix_product_card_versions_trigger_event_id", "product_card_versions", ["trigger_event_id"])

    op.create_table(
        "domain_event_records",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_domain_event_records_aggregate_time",
        "domain_event_records",
        ["aggregate_type", "aggregate_id", "occurred_at"],
    )
    op.create_index(
        "ix_domain_event_records_event_type_time",
        "domain_event_records",
        ["event_type", "occurred_at"],
    )
    op.create_index("ix_domain_event_records_correlation_id", "domain_event_records", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_domain_event_records_correlation_id", table_name="domain_event_records")
    op.drop_index("ix_domain_event_records_event_type_time", table_name="domain_event_records")
    op.drop_index("ix_domain_event_records_aggregate_time", table_name="domain_event_records")
    op.drop_table("domain_event_records")

    op.drop_index("ix_product_card_versions_trigger_event_id", table_name="product_card_versions")
    op.drop_index("ix_product_card_versions_product_created", table_name="product_card_versions")
    op.drop_index("ix_product_card_versions_product_number", table_name="product_card_versions")
    op.drop_table("product_card_versions")

    op.drop_index("ix_product_card_drafts_product_id", table_name="product_card_drafts")
    op.drop_index("ix_product_card_drafts_product_status_updated", table_name="product_card_drafts")
    op.drop_table("product_card_drafts")
