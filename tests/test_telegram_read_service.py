import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.helpers import reload_app_modules


class TelegramReadServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "telegram_read_service_test.db"
        self.jsonl_path = Path(self.tmp.name) / "scrape_attempts.jsonl"
        self.block_jsonl_path = Path(self.tmp.name) / "blocked_patterns.jsonl"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(self.jsonl_path)
        os.environ["BLOCK_PATTERNS_JSONL"] = str(self.block_jsonl_path)
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

        from app.telegram_read_service import TelegramReadService
        self.service = TelegramReadService(self.db)

    async def asyncTearDown(self):
        await self.db._engine.dispose()
        os.environ.pop("SCRAPE_ATTEMPTS_JSONL", None)
        os.environ.pop("BLOCK_PATTERNS_JSONL", None)
        self.tmp.cleanup()

    async def test_get_recent_products_with_prices_empty_db_returns_empty(self):
        products, latest_by_product = await self.service.get_recent_products_with_prices(limit=20)
        self.assertEqual(products, [])
        self.assertEqual(latest_by_product, {})

    async def test_get_recent_products_with_prices_pairs_each_product_with_its_latest_price(self):
        p1, _ = await self.db.save_product(
            "https://example.com/a", {"name": "A", "price": 100, "availability": "in_stock"}
        )
        # Second save on the same product changes the price -> new PriceHistory row.
        await self.db.save_product(
            "https://example.com/a", {"name": "A", "price": 150, "availability": "in_stock"}
        )
        p2, _ = await self.db.save_product(
            "https://example.com/b", {"name": "B", "price": 200, "availability": "out_of_stock"}
        )

        products, latest_by_product = await self.service.get_recent_products_with_prices(limit=20)

        self.assertEqual({p.id for p in products}, {p1.id, p2.id})
        self.assertEqual(latest_by_product[p1.id].price, 150, "must be the LATEST price, not the first")
        self.assertEqual(latest_by_product[p2.id].price, 200)
        self.assertEqual(latest_by_product[p2.id].availability_status, "out_of_stock")

    async def test_get_recent_products_with_prices_respects_limit(self):
        for i in range(5):
            await self.db.save_product(
                f"https://example.com/item-{i}", {"name": f"Item {i}", "price": 10, "availability": "in_stock"}
            )

        products, _ = await self.service.get_recent_products_with_prices(limit=3)
        self.assertEqual(len(products), 3)

    async def test_get_status_counts_reflects_products_history_and_subscribers(self):
        await self.db.save_product("https://example.com/a", {"name": "A", "price": 100, "availability": "in_stock"})
        await self.db.save_product("https://example.com/a", {"name": "A", "price": 120, "availability": "in_stock"})
        await self.db.add_subscriber(111)
        await self.db.add_subscriber(222)

        n_products, n_history, n_subscribers = await self.service.get_status_counts()

        self.assertEqual(n_products, 1)
        self.assertEqual(n_history, 2, "two distinct price points recorded for the same product")
        self.assertEqual(n_subscribers, 2)

    async def test_get_subscriber_ids_returns_added_subscribers(self):
        await self.db.add_subscriber(111)
        await self.db.add_subscriber(222)

        ids = await self.service.get_subscriber_ids()

        self.assertEqual(set(ids), {111, 222})

    async def test_get_recent_price_changes_filters_by_window_and_orders_newest_first(self):
        product, _ = await self.db.save_product(
            "https://example.com/a", {"name": "A", "price": 100, "availability": "in_stock"}
        )
        # Directly seed history rows with controlled timestamps (save_product always
        # uses "now", so we manipulate PriceHistory rows through the ORM for the
        # old/new distinction this test needs).
        from app.database import PriceHistory

        now = datetime.now(UTC)
        async with self.db.session() as s:
            s.add(PriceHistory(
                product_id=product.id, price=90, availability_status="in_stock",
                recorded_at=now - timedelta(hours=5),
            ))
            s.add(PriceHistory(
                product_id=product.id, price=80, availability_status="in_stock",
                recorded_at=now - timedelta(minutes=30),
            ))
            await s.commit()

        rows = await self.service.get_recent_price_changes(now - timedelta(hours=2), limit=20)

        prices = [ph.price for ph, _ in rows]
        self.assertIn(80, prices, "recent (30 min ago) change must be included")
        self.assertNotIn(90, prices, "old (5h ago) change must be excluded by the 2h window")
        self.assertEqual(rows[0][1].id, product.id)

    async def test_get_recent_price_changes_no_changes_in_window_returns_empty(self):
        rows = await self.service.get_recent_price_changes(datetime.now(UTC) - timedelta(hours=2), limit=20)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
