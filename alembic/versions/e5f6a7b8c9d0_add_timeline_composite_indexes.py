"""add timeline composite indexes

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-17 12:12:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_price_history_product_recorded",
        "price_history",
        ["product_id", "recorded_at"],
    )
    op.create_index(
        "ix_approval_records_product_created",
        "approval_records",
        ["product_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_records_product_created", table_name="approval_records")
    op.drop_index("ix_price_history_product_recorded", table_name="price_history")
