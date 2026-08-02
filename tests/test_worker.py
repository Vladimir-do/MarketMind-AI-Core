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
