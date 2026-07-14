import unittest
from unittest.mock import AsyncMock, patch

from app.telegram_card_research import build_card_research_message


class TelegramCardResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_card_research_message_uses_search_results(self):
        search = AsyncMock(return_value=[{"name": "РўРѕРІР°СЂ", "price": 100}])
        with patch("app.card_research.build_card_research_report", AsyncMock(return_value="report")) as report:
            result = await build_card_research_message("query", search=search)

        self.assertEqual(result, "report")
        search.assert_awaited_once_with("query", 10)
        report.assert_awaited_once_with("query", [{"name": "РўРѕРІР°СЂ", "price": 100}])
