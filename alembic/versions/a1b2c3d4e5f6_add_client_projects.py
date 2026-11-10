"""add client projects

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-07-17 16:20:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_projects",
        sa.Column("project_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("source_file_hash", sa.String(length=64), nullable=True),
        sa.Column("source_imported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("export_directory", sa.Text(), nullable=True),
    )
    op.create_index("ix_client_projects_status_updated", "client_projects", ["status", "updated_at"])

    op.create_table(
        "client_project_files",
        sa.Column("file_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("import_status", sa.String(length=32), nullable=False),
        sa.Column("import_errors_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "sha256", name="uq_client_project_files_project_sha256"),
    )
    op.create_index("ix_client_project_files_project_created", "client_project_files", ["project_id", "created_at"])

    op.create_table(
        "project_products",
        sa.Column("project_product_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "source_file_id",
            sa.String(length=64),
            sa.ForeignKey("client_project_files.file_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_row_index", sa.Integer(), nullable=True),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("latest_source_snapshot_json", sa.Text(), nullable=False),
        sa.Column("latest_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("effective_updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("project_id", "product_id", name="uq_project_products_project_product"),
    )
    op.create_index("ix_project_products_project_updated", "project_products", ["project_id", "updated_at"])
    op.create_index("ix_project_products_product_id", "project_products", ["product_id"])

    op.create_table(
        "project_exports",
        sa.Column("export_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("export_type", sa.String(length=32), nullable=False),
        sa.Column("marketplace_profile", sa.String(length=32), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("product_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_project_exports_project_created", "project_exports", ["project_id", "created_at"])

    op.create_table(
        "project_reports",
        sa.Column("report_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("client_projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_project_reports_project_created", "project_reports", ["project_id", "created_at"])

    op.add_column("product_card_drafts", sa.Column("project_id", sa.String(length=64), nullable=True))
    op.add_column("product_card_drafts", sa.Column("project_product_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_product_card_drafts_project_product_status",
        "product_card_drafts",
        ["project_id", "project_product_id", "status"],
    )

    op.add_column("product_card_versions", sa.Column("project_id", sa.String(length=64), nullable=True))
    op.add_column("product_card_versions", sa.Column("project_product_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_product_card_versions_project_product_number",
        "product_card_versions",
        ["project_id", "project_product_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_card_versions_project_product_number", table_name="product_card_versions")
    op.drop_column("product_card_versions", "project_product_id")
    op.drop_column("product_card_versions", "project_id")

    op.drop_index("ix_product_card_drafts_project_product_status", table_name="product_card_drafts")
    op.drop_column("product_card_drafts", "project_product_id")
    op.drop_column("product_card_drafts", "project_id")

    op.drop_index("ix_project_reports_project_created", table_name="project_reports")
    op.drop_table("project_reports")

    op.drop_index("ix_project_exports_project_created", table_name="project_exports")
    op.drop_table("project_exports")

    op.drop_index("ix_project_products_product_id", table_name="project_products")
    op.drop_index("ix_project_products_project_updated", table_name="project_products")
    op.drop_table("project_products")

    op.drop_index("ix_client_project_files_project_created", table_name="client_project_files")
    op.drop_table("client_project_files")

    op.drop_index("ix_client_projects_status_updated", table_name="client_projects")
    op.drop_table("client_projects")
