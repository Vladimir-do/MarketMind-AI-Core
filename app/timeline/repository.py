"""Database access for product timeline sources."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from app.database import ApprovalRecord, Database, PriceHistory, Product


class TimelineRepository:
    """Loads source rows required to build a product timeline."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_product(self, product_id: int) -> Product | None:
        async with self._db.session() as session:
            return await session.get(Product, product_id)

    async def get_price_history(
        self,
        product_id: int,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
    ) -> list[PriceHistory]:
        async with self._db.session() as session:
            stmt = select(PriceHistory).where(PriceHistory.product_id == product_id)
            if date_from is not None:
                stmt = stmt.where(PriceHistory.recorded_at >= date_from)
            if date_to is not None:
                stmt = stmt.where(PriceHistory.recorded_at <= date_to)
            result = await session.execute(
                stmt.order_by(desc(PriceHistory.recorded_at)).limit(limit)
            )
            return list(result.scalars().all())

    async def get_approval_records(
        self,
        product_id: int,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
    ) -> list[ApprovalRecord]:
        async with self._db.session() as session:
            stmt = select(ApprovalRecord).where(ApprovalRecord.product_id == str(product_id))
            if date_from is not None:
                stmt = stmt.where(ApprovalRecord.created_at >= date_from)
            if date_to is not None:
                stmt = stmt.where(ApprovalRecord.created_at <= date_to)
            result = await session.execute(
                stmt.order_by(desc(ApprovalRecord.created_at)).limit(limit)
            )
            return list(result.scalars().all())
