import io
import unittest
from unittest.mock import AsyncMock, patch

from app.telegram_exports import send_html_report, send_price_export


class TelegramExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_price_export_sends_csv_document(self):
        bot = AsyncMock()
        with patch("app.exporter.export_csv", AsyncMock(return_value=io.BytesIO(b"a,b\n1,2\n"))) as export_csv:
            await send_price_export(bot, object(), 123, "csv")

        export_csv.assert_awaited_once()
        bot.send_document.assert_awaited_once()
        chat_id, document = bot.send_document.await_args.args
        self.assertEqual(chat_id, 123)
        self.assertTrue(document.filename.startswith("prices_"))
        self.assertTrue(document.filename.endswith(".csv"))
        self.assertIn("CSV", bot.send_document.await_args.kwargs["caption"])

    async def test_send_html_report_requires_connected_bot(self):
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            await send_html_report(None, object(), 123)

    async def test_send_html_report_sends_html_document(self):
        bot = AsyncMock()
        with patch("app.reporter.export_html_report", AsyncMock(return_value=io.BytesIO(b"<html></html>"))) as export_report:
            await send_html_report(bot, object(), 456)

        export_report.assert_awaited_once()
        bot.send_document.assert_awaited_once()
        chat_id, document = bot.send_document.await_args.args
        self.assertEqual(chat_id, 456)
        self.assertTrue(document.filename.startswith("report_"))
        self.assertTrue(document.filename.endswith(".html"))
        self.assertEqual(bot.send_document.await_args.kwargs["parse_mode"], "HTML")
