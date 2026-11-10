"""CRUD-слой для CompetitorSnapshot — батчи снэпшотов конкурентов.

По образцу app.content_pipeline.artifact_store — версионируемые данные
без approval-семантики, группируются по batch_id (один запуск refresh).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from app.database import CompetitorSnapshot, Database

if TYPE_CHECKING:
    from app.parsers.base import ProductData


class CompetitorSnapshotStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_batch(
        self,
        *,
        project_id: str,
        project_product_id: str,
        product_id: int,
        search_query: str,
        products: list[tuple[str, ProductData]],
    ) -> tuple[str, list[CompetitorSnapshot]]:
        """products — список (marketplace, ProductData). Возвращает (batch_id, записи)."""
        batch_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        records: list[CompetitorSnapshot] = []
        async with self._db.session() as s:
            for marketplace, product in products:
                record = CompetitorSnapshot(
                    snapshot_id=uuid.uuid4().hex[:20],
                    batch_id=batch_id,
                    project_id=project_id,
                    project_product_id=project_product_id,
                    product_id=product_id,
                    marketplace=marketplace,
                    competitor_name=product.name,
                    competitor_url=product.url,
                    price=product.price,
                    old_price=product.old_price,
                    rating=product.rating,
                    reviews_count=product.reviews_count,
                    reviews_json=json.dumps(product.reviews, ensure_ascii=False) if product.reviews else None,
                    search_query=search_query,
                    created_at=now,
                )
                s.add(record)
                records.append(record)
            await s.commit()
            for record in records:
                await s.refresh(record)
        return batch_id, records

    async def get_latest_batch(self, *, project_id: str, project_product_id: str) -> list[CompetitorSnapshot]:
        async with self._db.session() as s:
            latest_batch_id = await s.scalar(
                select(CompetitorSnapshot.batch_id)
                .where(CompetitorSnapshot.project_id == project_id)
                .where(CompetitorSnapshot.project_product_id == project_product_id)
                .order_by(desc(CompetitorSnapshot.created_at))
                .limit(1)
            )
            if latest_batch_id is None:
                return []
            result = await s.execute(
                select(CompetitorSnapshot)
                .where(CompetitorSnapshot.project_id == project_id)
                .where(CompetitorSnapshot.project_product_id == project_product_id)
                .where(CompetitorSnapshot.batch_id == latest_batch_id)
                .order_by(CompetitorSnapshot.marketplace, desc(CompetitorSnapshot.rating))
            )
            return list(result.scalars().all())

    async def list_batches(
        self, *, project_id: str, project_product_id: str, limit: int = 20
    ) -> list[list[CompetitorSnapshot]]:
        async with self._db.session() as s:
            result = await s.execute(
                select(CompetitorSnapshot)
                .where(CompetitorSnapshot.project_id == project_id)
                .where(CompetitorSnapshot.project_product_id == project_product_id)
                .order_by(desc(CompetitorSnapshot.created_at))
            )
            rows = list(result.scalars().all())
        grouped: dict[str, list[CompetitorSnapshot]] = {}
        order: list[str] = []
        for row in rows:
            if row.batch_id not in grouped:
                grouped[row.batch_id] = []
                order.append(row.batch_id)
            grouped[row.batch_id].append(row)
        return [grouped[batch_id] for batch_id in order[:limit]]

    @staticmethod
    def reviews_of(record: CompetitorSnapshot) -> list[str]:
        if not record.reviews_json:
            return []
        try:
            return json.loads(record.reviews_json)
        except (TypeError, ValueError):
            return []
