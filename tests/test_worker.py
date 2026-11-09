import unittest
from unittest.mock import AsyncMock, patch

from app.worker import worker_add_urls


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_marketplace_messages_are_readable(self):
        messages = []

        async def notify(text: str):
            messages.append(text)

        with patch("app.worker.research_parse_failure", AsyncMock()):
            result = await worker_add_urls(AsyncMock(), ["https://example.com/item"], notify)

        joined = "\n".join(messages + [result])
        self.assertIn("Неизвестный маркетплейс", joined)
        self.assertIn("Добавлено", joined)
        self.assertIn("Ошибок", joined)
        for broken in ("Рќ", "Рћ", "СЃ", "вњ", "вќ", "рџ", "в‚"):
            self.assertNotIn(broken, joined)

    async def test_blocked_ozon_url_is_saved_as_provisional_record(self):
        url = "https://www.ozon.ru/product/kompleks-vitaminov-gruppy-v-magniy-immunit-shipuchie-tabletki-20-sht-823223431/"
        messages = []
        db = AsyncMock()

        class FakeOzonUpdater:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def add_urls(self, urls, callback=None):
                if callback:
                    await callback("Ozon blocked")
                return 0

        async def notify(text: str):
            messages.append(text)

        with patch("app.worker.OzonUpdater", FakeOzonUpdater), \
             patch("app.worker._wait_marketplace_window", AsyncMock()), \
             patch("app.worker._recommend_strategy", AsyncMock(return_value={"skip": False})), \
             patch("app.worker._mark_block_and_alert", AsyncMock()):
            result = await worker_add_urls(db, [url], notify)

        db.save_product.assert_awaited_once()
        saved_url, payload = db.save_product.await_args.args
        self.assertEqual(saved_url, url)
        self.assertIn("Kompleks vitaminov", payload["name"])
        self.assertIsNone(payload["price"])
        self.assertIsNone(payload["image_url"])
        self.assertEqual(payload["availability"], "draft")
        self.assertIn("Ссылок сохранено как черновик", result)
        self.assertTrue(any("не подтверждено" in m.lower() or "черновик" in m.lower() for m in messages))

    async def test_recently_blocked_ozon_url_is_saved_even_when_strategy_skips(self):
        url = "https://www.ozon.ru/product/kompleks-vitaminov-gruppy-v-magniy-immunit-shipuchie-tabletki-20-sht-823223431/?at=abc"
        messages = []
        recorded = []
        db = AsyncMock()

        async def notify(text: str):
            messages.append(text)

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "defer_same_url", "skip": True,
                    "reason": "same URL recently blocked by browser", "cooldown_sec": 600,
                }

            async def record_blocked_pattern(self, **kwargs):
                recorded.append(kwargs)

            async def save_product(self, product_url, payload):
                await db.save_product(product_url, payload)

        result = await worker_add_urls(FakeDB(), [url], notify)
        db.save_product.assert_awaited_once()
        saved_url, payload = db.save_product.await_args.args
        self.assertEqual(saved_url, url)
        self.assertEqual(payload["availability"], "draft")
        self.assertIsNone(payload["price"])
        self.assertIn("Ссылок сохранено как черновик: <b>1</b>", result)
        self.assertTrue(any("same URL recently blocked" in m for m in messages))
        self.assertTrue(any("черновик" in m.lower() for m in messages))
        self.assertEqual(recorded[0]["trigger"], "adaptive_skip")

    async def test_adaptive_strategy_can_skip_marketplace_url(self):
        messages = []
        recorded = []

        async def notify(text: str):
            messages.append(text)

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "defer_same_url",
                    "skip": True,
                    "skip_browser": True,
                    "reason": "same URL recently blocked by browser",
                    "cooldown_sec": 600,
                }

            async def record_blocked_pattern(self, **kwargs):
                recorded.append(kwargs)

        result = await worker_add_urls(
            FakeDB(),
            ["https://www.wildberries.ru/catalog/311895731/detail.aspx"],
            notify,
        )

        self.assertIn("Пропускаю wildberries", "\n".join(messages))
        self.assertIn("Ошибок: 1", result)
        self.assertEqual(recorded[0]["trigger"], "adaptive_skip")
        self.assertEqual(recorded[0]["strategy"], "defer_same_url")

    async def test_self_healing_strategy_can_skip_api_only_marketplace(self):
        messages = []
        recorded = []

        async def notify(text: str):
            messages.append(text)

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "self_heal_disable_api",
                    "skip": False,
                    "skip_api": True,
                    "skip_browser": False,
                    "reason": "3 recent API blocks in 60 min",
                    "cooldown_sec": 7200,
                }

            async def record_blocked_pattern(self, **kwargs):
                recorded.append(kwargs)

        result = await worker_add_urls(
            FakeDB(),
            ["https://www.wildberries.ru/catalog/311895731/detail.aspx"],
            notify,
        )

        self.assertIn("Skipping wildberries API route", "\n".join(messages))
        self.assertIn("Ошибок: 1", result)
        self.assertEqual(recorded[0]["trigger"], "adaptive_api_cooldown")
        self.assertEqual(recorded[0]["strategy"], "self_heal_disable_api")
