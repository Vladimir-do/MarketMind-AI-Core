import unittest
from unittest.mock import AsyncMock, patch

from app.card_research import build_card_research_report


class CardResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_report_contains_price_summary_and_keywords(self):
        with patch("app.card_research.ai_is_available", return_value=False):
            report = await build_card_research_report(
                "держатель телефона",
                [
                    {"name": "Держатель телефона автомобильный магнитный", "price": 500, "url": "https://example.com/1"},
                    {"name": "Держатель телефона в машину на панель", "price": 700, "url": "https://example.com/2"},
                    {"name": "Автомобильный держатель смартфона", "price": 900, "url": "https://example.com/3"},
                ],
            )

        self.assertIn("Найдено товаров", report)
        self.assertIn("медиана <b>700 ₽</b>", report)
        self.assertIn("держатель", report.lower())
        self.assertIn("Топ конкурентов", report)

    async def test_ai_recommendations_are_appended_when_available(self):
        with (
            patch("app.card_research.ai_is_available", return_value=True),
            patch("app.card_research.ask_ai", new=AsyncMock(return_value="SEO: Держатель телефона автомобильный")),
        ):
            report = await build_card_research_report(
                "держатель телефона",
                [{"name": "Держатель телефона автомобильный", "price": 500, "url": "https://example.com/1"}],
            )

        self.assertIn("AI-рекомендации", report)
        self.assertIn("SEO:", report)

    async def test_empty_report_is_clear(self):
        with patch("app.card_research.ai_is_available", return_value=False):
            report = await build_card_research_report("неизвестный товар", [])

        self.assertIn("Ничего не найдено", report)


if __name__ == "__main__":
    unittest.main()
