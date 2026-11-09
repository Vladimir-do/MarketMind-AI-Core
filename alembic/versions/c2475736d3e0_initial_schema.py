"""initial schema

Revision ID: c2475736d3e0
Revises:
Create Date: 2026-07-14 16:45:11.419913

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2475736d3e0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- products ---
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url_hash", sa.String(32), nullable=False, unique=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_check", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_products_url_hash", "products", ["url_hash"])

    # --- price_history ---
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("availability_status", sa.String(20), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_price_history_recorded_at", "price_history", ["recorded_at"])
    op.create_index("ix_price_history_product_id", "price_history", ["product_id"])

    # --- scrape_attempts ---
    op.create_table(
        "scrape_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("site", sa.Text(), nullable=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(80), nullable=True),
        sa.Column("parser_used", sa.String(120), nullable=True),
        sa.Column("fetch_status", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("proxy", sa.Text(), nullable=True),
        sa.Column("browser_profile", sa.Text(), nullable=True),
        sa.Column("strategy", sa.String(80), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("next_best_strategy", sa.String(120), nullable=True),
        sa.Column("error_class", sa.String(120), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scrape_attempts_recorded_at", "scrape_attempts", ["recorded_at"])
    op.create_index("ix_scrape_attempts_marketplace_recorded", "scrape_attempts", ["marketplace", "recorded_at"])
    op.create_index("ix_scrape_attempts_product_id", "scrape_attempts", ["product_id"])

    # --- blocked_patterns ---
    op.create_table(
        "blocked_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url_hash", sa.String(32), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(80), nullable=False),
        sa.Column("proxy", sa.Text(), nullable=True),
        sa.Column("browser_profile", sa.Text(), nullable=True),
        sa.Column("strategy", sa.String(80), nullable=True),
        sa.Column("cooldown_sec", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_class", sa.String(120), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_blocked_patterns_url_hash", "blocked_patterns", ["url_hash"])
    op.create_index("ix_blocked_patterns_marketplace", "blocked_patterns", ["marketplace"])
    op.create_index("ix_blocked_patterns_recorded_at", "blocked_patterns", ["recorded_at"])
    op.create_index("ix_blocked_patterns_marketplace_recorded", "blocked_patterns", ["marketplace", "recorded_at"])
    op.create_index("ix_blocked_patterns_trigger_recorded", "blocked_patterns", ["trigger", "recorded_at"])

    # --- subscribers ---
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_subscribers_user_id", "subscribers", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("subscribers")
    op.drop_table("blocked_patterns")
    op.drop_table("scrape_attempts")
    op.drop_table("price_history")
    op.drop_table("products")
