import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.telegram_ai_reports import build_price_alerts_message, build_price_forecast_message


class TelegramAiReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_forecast_reports_empty_database(self):
        db = SimpleNamespace(get_all_products=AsyncMock(return_value=[]))

        message = await build_price_forecast_message(db)

        self.assertIn("Р‘Р°Р·Р°", message)

    async def test_forecast_includes_product_with_enough_prices(self):
        db = SimpleNamespace(
            get_all_products=AsyncMock(return_value=[SimpleNamespace(id=1, name="РўРѕРІР°СЂ")])
        )
        analyzer = Mock()
        analyzer._get_prices = AsyncMock(return_value=[100, 110, 120])

        with patch("app.ai_analyzer.DeepAnalyzer", return_value=analyzer):
            message = await build_price_forecast_message(db)

        self.assertIn("РџСЂРѕРіРЅРѕР·", message)
        self.assertIn("РўРѕРІР°СЂ", message)

    async def test_alerts_reports_empty_list(self):
        analyzer = Mock()
        analyzer.price_alert_check = AsyncMock(return_value=[])

        with patch("app.ai_analyzer.DeepAnalyzer", return_value=analyzer):
            message = await build_price_alerts_message(object())

        self.assertIn("РђРєС‚РёРІРЅС‹С…", message)
