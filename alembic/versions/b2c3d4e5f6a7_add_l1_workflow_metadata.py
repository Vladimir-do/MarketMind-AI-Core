"""add l1 workflow metadata

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17 18:10:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("client_project_files", sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="local-import-v1"))
    op.add_column("client_project_files", sa.Column("encoding", sa.String(length=64), nullable=True))
    op.add_column("client_project_files", sa.Column("delimiter", sa.String(length=8), nullable=True))
    op.add_column("client_project_files", sa.Column("selected_sheet", sa.Text(), nullable=True))
    op.add_column("client_project_files", sa.Column("successful_rows", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("client_project_files", sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("client_project_files", sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("client_project_files", sa.Column("import_summary_json", sa.Text(), nullable=True))

    op.add_column("project_exports", sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="local-export-v1"))
    op.add_column("project_exports", sa.Column("checksum", sa.String(length=64), nullable=True))
    op.add_column("project_exports", sa.Column("manifest_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_exports", "manifest_json")
    op.drop_column("project_exports", "checksum")
    op.drop_column("project_exports", "schema_version")

    op.drop_column("client_project_files", "import_summary_json")
    op.drop_column("client_project_files", "error_count")
    op.drop_column("client_project_files", "warning_count")
    op.drop_column("client_project_files", "successful_rows")
    op.drop_column("client_project_files", "selected_sheet")
    op.drop_column("client_project_files", "delimiter")
    op.drop_column("client_project_files", "encoding")
    op.drop_column("client_project_files", "schema_version")
