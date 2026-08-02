"""Tests for CompetitorSnapshotStore (competitor_snapshots CRUD + batching)."""

from __future__ import annotations

import os
import unittest

from tests.helpers import reload_app_modules


def _product(name="Конкурент А", price=990, rating=4.5, reviews=None, url="https://example.test/1"):
    from app.parsers.base import ProductData

    return ProductData(
        name=name,
        price=price,
        old_price=None,
        discount_pct=None,
        availability="in_stock",
        url=url,
        image_url=None,
        rating=rating,
        reviews_count=42,
        marketplace="wildberries",
        reviews=reviews,
    )


class CompetitorSnapshotStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.competitor_analysis.store import CompetitorSnapshotStore
        from app.database import Database

        self.db = Database()
        await self.db.init()
        self.store = CompetitorSnapshotStore(self.db)

    async def asyncTearDown(self):
        await self.db._engine.dispose()

    async def test_save_batch_and_get_latest(self):
        batch_id, records = await self.store.save_batch(
            project_id="proj-1",
            project_product_id="pp-1",
            product_id=1,
            search_query="термокружка",
            products=[("wildberries", _product())],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].batch_id, batch_id)

        latest = await self.store.get_latest_batch(project_id="proj-1", project_product_id="pp-1")
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].competitor_name, "Конкурент А")

    async def test_reviews_json_round_trips(self):
        _, records = await self.store.save_batch(
            project_id="proj-1",
            project_product_id="pp-1",
            product_id=1,
            search_query="термокружка",
            products=[("wildberries", _product(reviews=["Хороший товар", "Держит тепло"]))],
        )
        self.assertEqual(self.store.reviews_of(records[0]), ["Хороший товар", "Держит тепло"])

    async def test_reviews_of_returns_empty_list_when_none(self):
        _, records = await self.store.save_batch(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            search_query="q", products=[("wildberries", _product(reviews=None))],
        )
        self.assertEqual(self.store.reviews_of(records[0]), [])

    async def test_new_batch_replaces_latest_but_keeps_history(self):
        first_batch_id, _ = await self.store.save_batch(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            search_query="q", products=[("wildberries", _product(name="Старый конкурент"))],
        )
        second_batch_id, _ = await self.store.save_batch(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            search_query="q", products=[("wildberries", _product(name="Новый конкурент"))],
        )
        self.assertNotEqual(first_batch_id, second_batch_id)

        latest = await self.store.get_latest_batch(project_id="proj-1", project_product_id="pp-1")
        self.assertEqual(latest[0].competitor_name, "Новый конкурент")

        history = await self.store.list_batches(project_id="proj-1", project_product_id="pp-1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0][0].batch_id, second_batch_id)
        self.assertEqual(history[1][0].batch_id, first_batch_id)

    async def test_get_latest_batch_empty_when_no_data(self):
        latest = await self.store.get_latest_batch(project_id="proj-x", project_product_id="pp-x")
        self.assertEqual(latest, [])

    async def test_batches_isolated_per_project_product(self):
        await self.store.save_batch(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            search_query="q", products=[("wildberries", _product())],
        )
        latest_other = await self.store.get_latest_batch(project_id="proj-1", project_product_id="pp-2")
        self.assertEqual(latest_other, [])


if __name__ == "__main__":
    unittest.main()
