"""Tests for the Store Analytics layer."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import reload_app_modules


class StoreAnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "analytics_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

    async def asyncTearDown(self):
        await self.db._engine.dispose()
        os.environ.pop("SCRAPE_ATTEMPTS_JSONL", None)
        os.environ.pop("BLOCK_PATTERNS_JSONL", None)
        self.tmp.cleanup()

    async def test_store_summary_empty_db(self):
        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        summary = await analyzer.get_store_summary()
        self.assertEqual(summary.total_products, 0)
        self.assertEqual(summary.average_score, 0.0)
        self.assertEqual(summary.products_below_threshold, 0)
        self.assertIsNone(summary.marketplace)

    async def test_store_summary_with_products(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/100",
            {"name": "Хороший товар", "price": 2500, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/200",
            {"name": "Другой товар", "price": 1500, "availability": "in_stock"},
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        summary = await analyzer.get_store_summary()
        self.assertEqual(summary.total_products, 2)
        self.assertGreaterEqual(summary.average_score, 0)
        self.assertIsInstance(summary.score_distribution.distribution, dict)
        self.assertIsInstance(summary.price_stats.avg_price, float)

    async def test_score_distribution(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/300",
            {"name": "Товар для распределения", "price": 1000, "availability": "in_stock"},
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        dist = await analyzer.get_score_distribution()
        self.assertEqual(dist.total, 1)
        self.assertGreaterEqual(dist.average_score, 0)
        # A product with only name+price gets "poor" tier (missing brand, category, etc.)
        self.assertTrue(len(dist.distribution) > 0)

    async def test_top_issues(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/400",
            {"name": "Товар с проблемами", "price": None, "availability": "in_stock"},
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        issues = await analyzer.get_top_issues(limit=5)
        self.assertIsInstance(issues, list)
        # A product without price should have at least one issue
        self.assertGreater(len(issues), 0)
        self.assertEqual(issues[0].severity, "critical")

    async def test_products_needing_attention(self):
        # Empty name → low score
        await self.db.save_product(
            "https://www.ozon.ru/product/500",
            {"name": "", "price": 500, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.ozon.ru/product/501",
            {
                "name": "Полностью заполненный товар с длинным описанием",
                "price": 1000,
                "availability": "in_stock",
                "brand": "TestBrand",
                "category": "Electronics",
            },
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        attention = await analyzer.get_products_needing_attention(threshold=50)
        self.assertIsInstance(attention, list)
        # The empty-name product should be flagged
        ids = {a.product_id for a in attention}
        self.assertTrue(len(ids) >= 1)

    async def test_price_statistics(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/600",
            {"name": "Дешёвый", "price": 100, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.ozon.ru/product/601",
            {"name": "Дорогой", "price": 5000, "availability": "in_stock"},
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        stats = await analyzer.get_price_statistics()
        self.assertEqual(stats.total_with_price, 2)
        self.assertEqual(stats.min_price, 100)
        self.assertEqual(stats.max_price, 5000)
        self.assertAlmostEqual(stats.avg_price, 2550.0, places=0)

    async def test_import_history(self):
        # Record a scrape attempt
        await self.db.record_scrape_attempt(
            url="https://www.ozon.ru/product/700",
            marketplace="ozon",
            source="api",
            status="ok",
            latency_ms=120,
        )
        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        history = await analyzer.get_import_history(days=1)
        self.assertIsInstance(history, list)
        # Should have at least one day with an import
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0].successes, 1)

    async def test_marketplace_comparison(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/800",
            {"name": "Ozon товар", "price": 1000, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/801",
            {"name": "WB товар", "price": 2000, "availability": "in_stock"},
        )

        from app.analytics.store_analyzer import StoreAnalyzer

        analyzer = StoreAnalyzer(self.db)
        comparison = await analyzer.get_marketplace_comparison()
        self.assertIsInstance(comparison, list)
        mp_names = {c.marketplace for c in comparison}
        self.assertIn("ozon", mp_names)
        self.assertIn("wildberries", mp_names)


if __name__ == "__main__":
    unittest.main()
