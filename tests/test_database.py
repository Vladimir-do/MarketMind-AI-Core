import json
import os
import tempfile
import unittest
import asyncio
from pathlib import Path

from tests.helpers import reload_app_modules


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "parser_test.db"
        self.jsonl_path = Path(self.tmp.name) / "scrape_attempts.jsonl"
        self.block_jsonl_path = Path(self.tmp.name) / "blocked_patterns.jsonl"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(self.jsonl_path)
        os.environ["BLOCK_PATTERNS_JSONL"] = str(self.block_jsonl_path)
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

    async def asyncTearDown(self):
        await self.db._engine.dispose()
        os.environ.pop("SCRAPE_ATTEMPTS_JSONL", None)
        os.environ.pop("BLOCK_PATTERNS_JSONL", None)
        os.environ.pop("ADAPTIVE_COOLDOWN_STEPS", None)
        os.environ.pop("ADAPTIVE_PREDICTIVE_HEAT_THRESHOLD", None)
        os.environ.pop("ADAPTIVE_API_BLOCK_THRESHOLD", None)
        self.tmp.cleanup()

    async def test_save_product_creates_history_only_when_price_or_status_changes(self):
        product, changed = await self.db.save_product(
            "https://example.com/item",
            {
                "name": "Phone Stand",
                "price": 1000,
                "availability": "in_stock",
                "image_url": "https://example.com/image.jpg",
            },
        )
        self.assertTrue(changed)

        same_product, changed = await self.db.save_product(
            "https://example.com/item",
            {
                "name": "Phone Stand",
                "price": 1000,
                "availability": "in_stock",
                "image_url": "https://example.com/image.jpg",
            },
        )
        self.assertEqual(product.id, same_product.id)
        self.assertFalse(changed)

        _, changed = await self.db.save_product(
            "https://example.com/item",
            {
                "name": "Phone Stand",
                "price": 900,
                "availability": "in_stock",
                "image_url": "https://example.com/image.jpg",
            },
        )
        self.assertTrue(changed)

        products = await self.db.get_all_products()
        self.assertEqual(len(products), 1)
        last = await self.db.get_last_price(product.id)
        self.assertEqual(last.price, 900)

    def test_url_hash_is_stable(self):
        url_to_hash = self.database_module.url_to_hash
        self.assertEqual(url_to_hash("x"), url_to_hash("x"))
        self.assertNotEqual(url_to_hash("x"), url_to_hash("y"))
        self.assertEqual(len(url_to_hash("x")), 32)

    async def test_save_product_keeps_existing_image_when_update_has_none(self):
        product, _ = await self.db.save_product(
            "https://example.com/item",
            {
                "name": "Phone Stand",
                "price": 1000,
                "availability": "in_stock",
                "image_url": "https://example.com/image.jpg",
            },
        )

        await self.db.save_product(
            "https://example.com/item",
            {
                "name": "Phone Stand",
                "price": 950,
                "availability": "in_stock",
                "image_url": None,
            },
        )

        products = await self.db.get_all_products()
        self.assertEqual(products[0].id, product.id)
        self.assertEqual(products[0].image_url, "https://example.com/image.jpg")

    async def test_get_latest_product_returns_most_recently_checked(self):
        first, _ = await self.db.save_product(
            "https://example.com/first",
            {"name": "First", "price": 100, "availability": "in_stock"},
        )
        second, _ = await self.db.save_product(
            "https://example.com/second",
            {"name": "Second", "price": 200, "availability": "in_stock"},
        )

        latest = await self.db.get_latest_product()

        self.assertEqual(latest.id, second.id)
        self.assertNotEqual(latest.id, first.id)

    async def test_record_scrape_attempt_stores_measurable_signal(self):
        await self.db.record_scrape_attempt(
            url="https://www.ozon.ru/product/test",
            marketplace="ozon",
            source="api",
            status="blocked",
            http_status=403,
            latency_ms=123,
            error_class=None,
            error_text="403 forbidden",
            errors=["403 forbidden"],
            warnings=["api blocked"],
            confidence=0.2,
            next_best_strategy="browser_if_allowed",
        )

        attempts = await self.db.get_recent_scrape_attempts()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].marketplace, "ozon")
        self.assertEqual(attempts[0].source, "api")
        self.assertEqual(attempts[0].status, "blocked")
        self.assertEqual(attempts[0].site, "www.ozon.ru")
        self.assertEqual(attempts[0].task_type, "marketplace_product")
        self.assertEqual(attempts[0].parser_used, "ozon")
        self.assertFalse(attempts[0].success)
        self.assertEqual(attempts[0].http_status, 403)
        self.assertEqual(attempts[0].latency_ms, 123)
        self.assertEqual(attempts[0].errors, '["403 forbidden"]')
        self.assertEqual(attempts[0].warnings, '["api blocked"]')
        self.assertEqual(attempts[0].confidence, 0.2)
        self.assertEqual(attempts[0].next_best_strategy, "browser_if_allowed")

        lines = self.jsonl_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["marketplace"], "ozon")
        self.assertEqual(payload["source"], "api")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["site"], "www.ozon.ru")
        self.assertEqual(payload["task_type"], "marketplace_product")
        self.assertEqual(payload["parser_used"], "ozon")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["http_status"], 403)
        self.assertEqual(payload["latency_ms"], 123)
        self.assertEqual(payload["errors"], '["403 forbidden"]')
        self.assertEqual(payload["warnings"], '["api blocked"]')
        self.assertEqual(payload["confidence"], 0.2)
        self.assertEqual(payload["next_best_strategy"], "browser_if_allowed")
        self.assertIn("recorded_at", payload)

        patterns = await self.db.get_recent_blocked_patterns(marketplace="ozon")
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].trigger, "http_403")
        self.assertEqual(patterns[0].source, "api")
        self.assertTrue(self.block_jsonl_path.exists())

    async def test_recommend_scrape_strategy_skips_recent_browser_block(self):
        await self.db.record_blocked_pattern(
            url="https://www.ozon.ru/product/test",
            marketplace="ozon",
            source="browser",
            status="blocked",
            trigger="abt-challenge",
            strategy="incident=fab_chlg_1",
            cooldown_sec=600,
        )

        decision = await self.db.recommend_scrape_strategy(
            "ozon",
            url="https://www.ozon.ru/product/test",
        )

        self.assertTrue(decision["skip"])
        self.assertTrue(decision["skip_browser"])
        self.assertEqual(decision["strategy"], "defer_same_url")

    async def test_recommend_scrape_strategy_skips_browser_after_repeated_browser_blocks(self):
        for idx in range(3):
            await self.db.record_blocked_pattern(
                url=f"https://www.ozon.ru/product/{idx}",
                marketplace="ozon",
                source="browser",
                status="blocked",
                trigger="abt-challenge",
            )

        decision = await self.db.recommend_scrape_strategy(
            "ozon",
            url="https://www.ozon.ru/product/new",
        )

        self.assertFalse(decision["skip"])
        self.assertTrue(decision["skip_browser"])
        self.assertEqual(decision["strategy"], "api_only_browser_cooldown")

    async def test_recommend_scrape_strategy_skips_browser_after_three_recent_browser_failures(self):
        for idx, status in enumerate(("blocked", "error", "parse_error")):
            await self.db.record_scrape_attempt(
                url=f"https://www.ozon.ru/product/browser-fail-{idx}",
                marketplace="ozon",
                source="browser",
                status=status,
                latency_ms=100 + idx,
                warnings=["browser did not help"],
            )

        decision = await self.db.recommend_scrape_strategy(
            "ozon",
            url="https://www.ozon.ru/product/new",
        )

        self.assertFalse(decision["skip"])
        self.assertTrue(decision["skip_browser"])
        self.assertEqual(decision["strategy"], "api_only_browser_cooldown")
        self.assertEqual(decision["next_best_strategy"], "api_or_structured_source_only")
        self.assertIn("3 recent browser failures", decision["reason"])

    async def test_marketplace_health_scores_reputation_and_dynamic_cooldown(self):
        os.environ["ADAPTIVE_COOLDOWN_STEPS"] = "1:300,2:1800,3:7200"
        await self.db.record_scrape_attempt(
            url="https://www.ozon.ru/product/ok",
            marketplace="ozon",
            source="browser",
            status="ok",
            latency_ms=100,
            proxy="http://proxy-1",
            browser_profile="profile_1",
        )
        for idx in range(3):
            await self.db.record_blocked_pattern(
                url=f"https://www.ozon.ru/product/blocked-{idx}",
                marketplace="ozon",
                source="browser",
                status="blocked",
                trigger="abt-challenge",
                proxy="http://proxy-2",
                browser_profile="profile_2",
            )

        health = await self.db.get_marketplace_health("ozon")

        self.assertGreater(health["heat_score"], 0)
        self.assertEqual(health["dynamic_cooldown_sec"], 7200)
        self.assertEqual(health["preferred_browser_profile"], "profile_1")
        self.assertTrue(health["browser_reputation"]["profile_2"]["heavily_blocked"])
        self.assertTrue(health["proxy_reputation"]["http://proxy-2"]["heavily_blocked"])
        self.assertIn("browser", health["source_scores"])

    async def test_recommend_scrape_strategy_can_disable_api_route(self):
        os.environ["ADAPTIVE_API_BLOCK_THRESHOLD"] = "3"
        for idx in range(3):
            await self.db.record_blocked_pattern(
                url=f"https://www.wildberries.ru/catalog/{idx}/detail.aspx",
                marketplace="wildberries",
                source="api",
                status="blocked",
                trigger="http_403",
            )

        decision = await self.db.recommend_scrape_strategy(
            "wildberries",
            url="https://www.wildberries.ru/catalog/999/detail.aspx",
        )

        self.assertTrue(decision["skip_api"])
        self.assertEqual(decision["strategy"], "self_heal_disable_api")
        self.assertGreaterEqual(decision["cooldown_sec"], 7200)

    async def test_recommend_scrape_strategy_predicts_high_heat_before_next_browser_try(self):
        os.environ["ADAPTIVE_PREDICTIVE_HEAT_THRESHOLD"] = "0.7"
        await self.db.record_blocked_pattern(
            url="https://market.yandex.ru/product--phone/123",
            marketplace="yandex_market",
            source="browser",
            status="blocked",
            trigger="captcha",
        )

        decision = await self.db.recommend_scrape_strategy(
            "yandex_market",
            url="https://market.yandex.ru/product--phone/456",
        )

        self.assertEqual(decision["strategy"], "predictive_heat_cooldown")
        self.assertTrue(decision["skip_browser"])
        self.assertGreaterEqual(decision["heat_score"], 0.7)

    async def test_subscribers_are_persisted_without_duplicates(self):
        await self.db.add_subscriber(123)
        await self.db.add_subscriber(123)
        await self.db.add_subscriber(456)

        self.assertEqual(await self.db.get_subscribers(), [123, 456])
        self.assertEqual(await self.db.get_subscriber_count(), 2)

        await self.db.remove_subscriber(123)

        self.assertEqual(await self.db.get_subscribers(), [456])
        self.assertEqual(await self.db.get_subscriber_count(), 1)
