import unittest
from unittest.mock import AsyncMock, patch

from app.telegram_marketplace_utils import (
    _search_competitors_with_fallback,
    build_competitor_search_status,
)


class TelegramMarketplaceUtilsTests(unittest.IsolatedAsyncioTestCase):
    def test_search_status_explains_ozon_cooldown_and_escapes_query(self):
        with patch(
            "app.telegram_marketplace_utils.ozon_search_blocked_message",
            return_value="Поиск Ozon временно недоступен: antibot. Повторите через 20 мин.",
        ):
            status = build_competitor_search_status("держатель <для> телефона")

        self.assertIn("Ozon временно недоступен", status)
        self.assertIn("Wildberries и Яндекс Маркете", status)
        self.assertIn("держатель &lt;для&gt; телефона", status)
        self.assertNotIn("держатель <для> телефона", status)

    def test_search_status_keeps_normal_message_when_ozon_available(self):
        with patch(
            "app.telegram_marketplace_utils.ozon_search_blocked_message",
            return_value=None,
        ):
            status = build_competitor_search_status("держатель телефона")

        self.assertIn("Ищу конкурентов", status)
        self.assertIn("держатель телефона", status)
        self.assertNotIn("временно недоступен", status)

    async def test_competitor_search_skips_blocked_ozon_but_keeps_other_markets(self):
        results = {
            "wildberries": [{"name": "WB product", "price": 100}],
            "ozon": [],
            "yandex_market": [{"name": "YM product", "price": 120}],
        }
        search = AsyncMock(return_value=results)
        with (
            patch(
                "app.telegram_marketplace_utils.ozon_search_blocked_message",
                return_value="Ozon blocked",
            ),
            patch("app.telegram_marketplace_utils.search_all_marketplaces", search),
        ):
            competitors = await _search_competitors_with_fallback("query", max_per_site=8)

        search.assert_awaited_once_with("query", max_per_site=8, exclude_marketplaces=("ozon",))
        self.assertEqual([item["marketplace"] for item in competitors], ["wildberries", "yandex_market"])
        self.assertEqual([item["name"] for item in competitors], ["WB product", "YM product"])


if __name__ == "__main__":
    unittest.main()
