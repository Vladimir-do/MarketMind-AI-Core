"""Database access for product timeline sources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import desc, or_, select

from app.database import ApprovalRecord, Database, PriceHistory, Product
from app.domain.events.models import AggregateType
from app.domain.events.repository import DomainEventRepository
from app.domain.events.time import to_legacy_utc_naive

if TYPE_CHECKING:
    from datetime import datetime


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
        limit: int | None = None,
    ) -> list[PriceHistory]:
        async with self._db.session() as session:
            stmt = select(PriceHistory).where(PriceHistory.product_id == product_id)
            if date_from is not None:
                stmt = stmt.where(PriceHistory.recorded_at >= to_legacy_utc_naive(date_from))
            if date_to is not None:
                stmt = stmt.where(PriceHistory.recorded_at <= to_legacy_utc_naive(date_to))
            stmt = stmt.order_by(desc(PriceHistory.recorded_at))
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            if date_from is None:
                return rows

            predecessor_result = await session.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product_id)
                .where(PriceHistory.recorded_at < to_legacy_utc_naive(date_from))
                .order_by(desc(PriceHistory.recorded_at))
                .limit(1)
            )
            predecessor = predecessor_result.scalar_one_or_none()
            if predecessor is None:
                return rows
            by_id = {row.id: row for row in rows}
            by_id.setdefault(predecessor.id, predecessor)
            return list(by_id.values())

    async def get_approval_records(
        self,
        product_id: int,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int | None = None,
    ) -> list[ApprovalRecord]:
        async with self._db.session() as session:
            stmt = select(ApprovalRecord).where(ApprovalRecord.product_id == str(product_id))
            range_conditions = []
            for column in (
                ApprovalRecord.created_at,
                ApprovalRecord.reviewed_at,
                ApprovalRecord.applied_at,
                ApprovalRecord.rolled_back_at,
            ):
                condition = column.is_not(None)
                if date_from is not None:
                    condition = condition & (column >= to_legacy_utc_naive(date_from))
                if date_to is not None:
                    condition = condition & (column <= to_legacy_utc_naive(date_to))
                if date_from is not None or date_to is not None:
                    range_conditions.append(condition)
            if range_conditions:
                stmt = stmt.where(or_(*range_conditions))
            stmt = stmt.order_by(desc(ApprovalRecord.created_at))
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_persisted_events(self, product_id: int, *, limit: int = 1000, offset: int = 0):
        async with self._db.session() as session:
            return await DomainEventRepository(session).list_by_aggregate(
                AggregateType.PRODUCT.value,
                str(product_id),
                limit=limit,
                offset=offset,
            )
