"""Regression tests for P1 group BOT-HTML (Master Plan).

Root cause: Telegram messages built with parse_mode="HTML" interpolated
product names / AI-generated text without html.escape(). A name/comment
containing '<', '>' or '&' makes Telegram reject the message
(TelegramBadRequest); aiogram's own dispatcher loop swallows any handler
exception that isn't caught locally (see loggers.event.exception in
Dispatcher._process_update) and sends nothing to the user — the bot looks
like it silently ignored the command.

Two-part fix, both covered here:
  1. A global @dp.errors() handler in app/bot.py — a safety net so ANY
     unhandled exception in ANY handler (not just these five) reaches the
     user as a visible error message instead of silence.
  2. html.escape() applied at the actual points where product names /
     AI text were interpolated unescaped: cmd_analyze, cmd_deals,
     cmd_anomalies (app/bot.py), market_overview (app/ai_analyzer.py),
     format_product_list (app/telegram_messages.py).
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.telegram_messages import format_product_list


class FakeUser:
    id = 42


class FakeMessage:
    def __init__(self):
        self.from_user = FakeUser()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class BotErrorEventHandlerTests(unittest.TestCase):
    """The global @dp.errors() safety net (app/bot.py::handle_unhandled_error)."""

    def test_unhandled_exception_notifies_user_instead_of_silence(self):
        import app.bot as bot_module

        message = FakeMessage()
        fake_event = SimpleNamespace(
            exception=RuntimeError("boom"),
            update=SimpleNamespace(message=message),
        )

        result = asyncio.run(bot_module.handle_unhandled_error(fake_event))

        self.assertTrue(result)
        self.assertEqual(len(message.answers), 1)
        self.assertIn("ошибка", message.answers[0].lower())

    def test_unhandled_exception_without_message_does_not_raise(self):
        import app.bot as bot_module

        fake_event = SimpleNamespace(exception=RuntimeError("boom"), update=SimpleNamespace())

        # Must not raise even when the update carries no .message (e.g. some
        # non-message update types) — this is a last-resort handler.
        result = asyncio.run(bot_module.handle_unhandled_error(fake_event))
        self.assertTrue(result)


class BotHtmlEscapingTests(unittest.TestCase):
    ADMIN_IDS_PATCH = [42]

    def test_cmd_analyze_escapes_ai_response(self):
        import app.bot as bot_module

        async def run():
            message = FakeMessage()
            with (
                patch.object(bot_module, "ADMIN_IDS", self.ADMIN_IDS_PATCH),
                patch.object(bot_module.agent, "analyze_portfolio", AsyncMock(return_value="Price < 100 & rising")),
            ):
                await bot_module.cmd_analyze(message)
            return message

        message = asyncio.run(run())
        combined = "\n".join(message.answers)
        self.assertIn("Price &lt; 100 &amp; rising", combined)
        self.assertNotIn("Price < 100 & rising", combined)

    def test_cmd_deals_escapes_product_name(self):
        import app.bot as bot_module

        deal = {
            "url": "https://example.com/p",
            "name": "Fisher & Price <toy>",
            "current_price": 100,
            "max_price": 200,
            "savings": 100,
            "savings_pct": 50,
        }

        async def run():
            message = FakeMessage()
            with (
                patch.object(bot_module, "ADMIN_IDS", self.ADMIN_IDS_PATCH),
                patch.object(bot_module.agent, "find_best_deals", AsyncMock(return_value=[deal])),
            ):
                await bot_module.cmd_deals(message)
            return message

        message = asyncio.run(run())
        combined = "\n".join(message.answers)
        self.assertIn("Fisher &amp; Price &lt;toy&gt;", combined)
        self.assertNotIn("Fisher & Price <toy>", combined)

    def test_cmd_anomalies_escapes_product_name_and_ai_comment(self):
        import app.bot as bot_module

        anomaly = {
            "direction": "📈",
            "url": "https://example.com/p",
            "name": "Cable & Wire <5m>",
            "old_price": 100,
            "new_price": 150,
            "change_pct": 50,
        }

        async def run():
            message = FakeMessage()
            with (
                patch.object(bot_module, "ADMIN_IDS", self.ADMIN_IDS_PATCH),
                patch.object(bot_module.agent, "detect_anomalies", AsyncMock(return_value=[anomaly])),
                patch.object(bot_module.agent, "_ask_claude", AsyncMock(return_value="Looks <suspicious> & odd")),
            ):
                await bot_module.cmd_anomalies(message)
            return message

        message = asyncio.run(run())
        combined = "\n".join(message.answers)
        self.assertIn("Cable &amp; Wire &lt;5m&gt;", combined)
        self.assertIn("Looks &lt;suspicious&gt; &amp; odd", combined)
        self.assertNotIn("Cable & Wire <5m>", combined)
        self.assertNotIn("Looks <suspicious> & odd", combined)

    def test_format_product_list_escapes_product_name(self):
        product = type("P", (), {"id": 1, "url": "https://example.com/a", "name": "Tea & Coffee <Set>"})()
        price = type("PH", (), {"price": 150, "availability_status": "in_stock"})()

        result = format_product_list([product], {1: price})

        self.assertIn("Tea &amp; Coffee &lt;Set&gt;", result)
        self.assertNotIn("Tea & Coffee <Set>", result)

    def test_format_product_list_escapes_url_attribute(self):
        product = type(
            "P", (), {"id": 1, "url": "https://example.com/' onmouseover='alert(1)", "name": "Safe name"}
        )()
        result = format_product_list([product], {})
        self.assertNotIn("onmouseover='alert(1)'", result)
        self.assertIn("&#x27;", result)

    def test_compare_prices_escapes_product_name_and_ai_response(self):
        from app.agent import PriceAgent

        agent = PriceAgent.__new__(PriceAgent)
        agent._ask_claude = AsyncMock(return_value="Buy <here> & now")

        async def run():
            return await agent.compare_prices("Phone <script>", 100, 120)

        result = asyncio.run(run())
        self.assertIn("Phone &lt;script&gt;", result)
        self.assertIn("Buy &lt;here&gt; &amp; now", result)
        self.assertNotIn("<script>", result)

    def test_market_overview_escapes_names_and_ai_comment(self):
        from app.ai_analyzer import DeepAnalyzer

        product = type("P", (), {"id": 1, "url": "https://example.com/a", "name": "Deal & Steal <Now>"})()
        db = SimpleNamespace(
            get_all_products=AsyncMock(return_value=[product]),
        )
        analyzer = DeepAnalyzer(db)

        async def run():
            with (
                patch.object(analyzer, "_get_prices", AsyncMock(return_value=[100, 90, 80])),
                patch.object(analyzer, "_claude", AsyncMock(return_value="Market is <hot> & volatile")),
            ):
                return await analyzer.market_overview()

        result = asyncio.run(run())
        self.assertIn("Deal &amp; Steal &lt;Now&gt;", result)
        self.assertIn("Market is &lt;hot&gt; &amp; volatile", result)
        self.assertNotIn("Deal & Steal <Now>", result)
        self.assertNotIn("Market is <hot> & volatile", result)


if __name__ == "__main__":
    unittest.main()
