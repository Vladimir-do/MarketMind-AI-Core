"""Read-only service for Telegram bot commands that need product/price data.

Owns the queries app/bot.py's read-only commands (cmd_list, cmd_status,
_broadcast_changes, cmd_update, cmd_reviews, handle_reviews_choice) need,
so those handlers depend on this service instead of touching app.database
directly. No Telegram imports here -- this module knows nothing about
aiogram, messages, or HTML formatting; it returns plain ORM
objects/dicts/tuples for the handler to format and send.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, desc, func, select

from app.database import Database, PriceHistory, Product

if TYPE_CHECKING:
    from datetime import datetime


class TelegramReadService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_recent_products_with_prices(
        self, limit: int = 20
    ) -> tuple[list[Product], dict[int, PriceHistory]]:
        """Most recently checked products, with each one's latest price/availability."""
        async with self._db.session() as s:
            products = (await s.execute(
                select(Product).order_by(Product.last_check.desc()).limit(limit)
            )).scalars().all()

        if not products:
            return [], {}

        product_ids = [p.id for p in products]
        latest_at = (
            select(
                PriceHistory.product_id.label("product_id"),
                func.max(PriceHistory.recorded_at).label("recorded_at"),
            )
            .where(PriceHistory.product_id.in_(product_ids))
            .group_by(PriceHistory.product_id)
            .subquery()
        )
        async with self._db.session() as s:
            latest_rows = (await s.execute(
                select(PriceHistory)
                .join(
                    latest_at,
                    and_(
                        PriceHistory.product_id == latest_at.c.product_id,
                        PriceHistory.recorded_at == latest_at.c.recorded_at,
                    ),
                )
            )).scalars().all()
        latest_by_product = {row.product_id: row for row in latest_rows}
        return list(products), latest_by_product

    async def get_status_counts(self) -> tuple[int, int, int]:
        """Returns (n_products, n_history, n_subscribers)."""
        async with self._db.session() as s:
            n_products = await s.scalar(select(func.count(Product.id)))
            n_history = await s.scalar(select(func.count(PriceHistory.id)))
        subscribers = await self._db.get_subscribers()
        return n_products, n_history, len(subscribers)

    async def get_subscriber_ids(self) -> list[int]:
        return await self._db.get_subscribers()

    async def get_recent_price_changes(
        self, since: datetime, limit: int = 20
    ) -> list[tuple[PriceHistory, Product]]:
        """Price/availability changes recorded since `since`, newest first."""
        async with self._db.session() as s:
            rows = (await s.execute(
                select(PriceHistory, Product)
                .join(Product)
                .where(PriceHistory.recorded_at >= since)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(limit)
            )).all()
        return list(rows)

    async def get_product_count(self) -> int:
        async with self._db.session() as s:
            return await s.scalar(select(func.count(Product.id)))

    async def get_recent_wildberries_products(self, limit: int = 5) -> list[Product]:
        """Most recently checked products whose URL is a Wildberries listing."""
        async with self._db.session() as s:
            products = (await s.execute(
                select(Product)
                .where(Product.url.contains("wildberries"))
                .order_by(Product.last_check.desc())
                .limit(limit)
            )).scalars().all()
        return list(products)

    async def get_product_by_id(self, product_id: int) -> Product | None:
        return await self._db.get_product_by_id(product_id)
