"""add approval_records

Revision ID: d4e5f6a7b8c9
Revises: c2475736d3e0
Create Date: 2026-07-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c2475736d3e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_id", sa.String(32), nullable=False, unique=True),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("suggestion_type", sa.String(32), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=True),
        sa.Column("after_value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_finding", sa.String(128), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("snapshot_before", sa.Text(), nullable=True),
        sa.Column("snapshot_after", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_approval_records_status", "approval_records", ["status"])
    op.create_index("ix_approval_records_product_id", "approval_records", ["product_id"])
    op.create_index("ix_approval_records_created_at", "approval_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_approval_records_created_at", "approval_records")
    op.drop_index("ix_approval_records_product_id", "approval_records")
    op.drop_index("ix_approval_records_status", "approval_records")
    op.drop_table("approval_records")
