"""Regression tests for D21 (app/bot.py export handlers swallowing errors
without logging).

Root cause: cmd_export_csv/cmd_export_excel caught send_price_export
failures with `except Exception as e: await message.answer(...)` and no
`logger` call at all -- unlike every other exception handler in bot.py,
which calls `logger.exception(...)`. A failed export was invisible in the
logs, only surfacing as a one-line message to the user in Telegram.

Fix: add `logger.exception(...)` to both handlers before the existing
`message.answer(...)` call. User-facing text, HTTP-equivalent behavior and
business logic are unchanged -- these tests assert both the logged
traceback AND the preserved user message.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class FakeUser:
    id = 42


class FakeChat:
    id = 42


class FakeMessage:
    def __init__(self):
        self.from_user = FakeUser()
        self.chat = FakeChat()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class BotExportErrorLoggingTests(unittest.TestCase):
    ADMIN_IDS_PATCH = [42]

    def test_cmd_export_csv_logs_exception_with_traceback(self):
        import app.bot as bot_module

        async def run():
            message = FakeMessage()
            with (
                patch.object(bot_module, "ADMIN_IDS", self.ADMIN_IDS_PATCH),
                patch.object(
                    bot_module, "send_price_export", AsyncMock(side_effect=RuntimeError("boom"))
                ),
                self.assertLogs("parser", level="ERROR") as logs,
            ):
                await bot_module.cmd_export_csv(message)
            return message, logs

        message, logs = asyncio.run(run())

        self.assertEqual(logs.records[0].exc_info[1].args[0], "boom")
        self.assertIn("CSV export error", logs.output[0])
        self.assertIn("Export error: boom", message.answers)

    def test_cmd_export_excel_logs_exception_with_traceback(self):
        import app.bot as bot_module

        async def run():
            message = FakeMessage()
            with (
                patch.object(bot_module, "ADMIN_IDS", self.ADMIN_IDS_PATCH),
                patch.object(
                    bot_module, "send_price_export", AsyncMock(side_effect=RuntimeError("boom"))
                ),
                self.assertLogs("parser", level="ERROR") as logs,
            ):
                await bot_module.cmd_export_excel(message)
            return message, logs

        message, logs = asyncio.run(run())

        self.assertEqual(logs.records[0].exc_info[1].args[0], "boom")
        self.assertIn("Excel export error", logs.output[0])
        self.assertIn("Export error: boom", message.answers)


if __name__ == "__main__":
    unittest.main()
