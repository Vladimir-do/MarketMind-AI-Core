"""add job records

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-07-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "job_records",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(length=120), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_job_records_job_type", "job_records", ["job_type"])
    op.create_index("ix_job_records_status", "job_records", ["status"])
    op.create_index("ix_job_records_status_updated", "job_records", ["status", "updated_at"])
    op.create_index("ix_job_records_type_created", "job_records", ["job_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_records_type_created", table_name="job_records")
    op.drop_index("ix_job_records_status_updated", table_name="job_records")
    op.drop_index("ix_job_records_status", table_name="job_records")
    op.drop_index("ix_job_records_job_type", table_name="job_records")
    op.drop_table("job_records")
