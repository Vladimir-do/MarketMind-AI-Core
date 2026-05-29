import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from python_socks import ProxyConnectionError


class BotStartupTests(unittest.TestCase):
    def test_start_bot_keeps_pending_updates_by_default(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        class FakeBot:
            drop_pending_updates = None
            commands = None

            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                FakeBot.drop_pending_updates = drop_pending_updates

            async def set_my_commands(self, commands):
                FakeBot.commands = commands

        fake_session = Mock()
        fake_session._connector_init = {}
        fake_session.close = AsyncMock()
        fake_db = Mock()
        fake_db.init = AsyncMock()
        fake_polling = AsyncMock()
        session_factory = Mock(return_value=fake_session)

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:abc"),
                patch.object(runtime, "AiohttpSession", session_factory),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", ""),
                patch.object(runtime, "TELEGRAM_DROP_PENDING_UPDATES", False),
                patch.object(bot_module.dp, "start_polling", fake_polling),
            ):
                return await bot_module.start_bot()

        self.assertTrue(asyncio.run(run()))
        self.assertFalse(FakeBot.drop_pending_updates)
        self.assertIn("blocks", [command.command for command in FakeBot.commands])
        self.assertIn("metrics", [command.command for command in FakeBot.commands])
        self.assertIn("health", [command.command for command in FakeBot.commands])
        self.assertEqual(session_factory.call_args.kwargs["proxy"], None)
        fake_polling.assert_awaited_once()
        fake_session.close.assert_awaited_once()
        self.assertIsNone(bot_module.bot)

    def test_telegram_reconnect_delay_caps_at_sixty_seconds(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        delays = [runtime.telegram_reconnect_delay(attempt) for attempt in range(1, 9)]

        self.assertEqual(delays, [1, 2, 5, 10, 30, 60, 60, 60])

    def test_telegram_network_error_does_not_stop_start_bot(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        calls = 0

        class FakeBot:
            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise TelegramNetworkError(method=Mock(), message="network timeout")

            async def set_my_commands(self, commands):
                return None

        session_factory = Mock()
        fake_session = Mock()
        fake_session._connector_init = {}
        fake_session.close = AsyncMock()
        session_factory.return_value = fake_session
        fake_db = Mock()
        fake_db.init = AsyncMock()

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:abc"),
                patch.object(runtime, "AiohttpSession", session_factory),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", ""),
                patch.object(bot_module.dp, "start_polling", AsyncMock()),
                patch.object(runtime.asyncio, "sleep", AsyncMock()) as sleep_mock,
            ):
                return await bot_module.start_bot(), sleep_mock

        result, sleep_mock = asyncio.run(run())

        self.assertTrue(result)
        self.assertEqual(calls, 2)
        fake_db.init.assert_awaited_once()
        self.assertEqual(session_factory.call_count, 2)
        sleep_mock.assert_awaited_once_with(1)
        self.assertEqual(fake_session.close.await_count, 2)
        self.assertIsNone(bot_module.bot)

    def test_start_bot_reconnects_when_polling_connection_drops(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        class FakeBot:
            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                return None

            async def set_my_commands(self, commands):
                return None

        sessions = []

        def session_factory(*args, **kwargs):
            fake_session = Mock()
            fake_session._connector_init = {}
            fake_session.close = AsyncMock()
            sessions.append(fake_session)
            return fake_session

        fake_db = Mock()
        fake_db.init = AsyncMock()
        polling_calls = 0

        async def fake_polling(_bot):
            nonlocal polling_calls
            polling_calls += 1
            if polling_calls == 1:
                raise TelegramNetworkError(method=Mock(), message="WinError 64")
            return None

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:abc"),
                patch.object(runtime, "AiohttpSession", side_effect=session_factory),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", ""),
                patch.object(runtime, "TELEGRAM_DROP_PENDING_UPDATES", False),
                patch.object(bot_module.dp, "start_polling", side_effect=fake_polling),
                patch.object(runtime.asyncio, "sleep", AsyncMock()) as sleep_mock,
            ):
                result = await bot_module.start_bot()
                return result, sleep_mock

        result, sleep_mock = asyncio.run(run())

        self.assertTrue(result)
        self.assertEqual(polling_calls, 2)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sleep_mock.await_args.args[0], 1)
        self.assertTrue(all(session.close.await_count == 1 for session in sessions))
        self.assertIsNone(bot_module.bot)

    def test_bad_proxy_falls_back_to_direct_mode(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        sessions = []

        class FakeBot:
            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                if self.session.proxy == "socks5://127.0.0.1:10808":
                    raise ProxyConnectionError("Couldn't connect to proxy 127.0.0.1:10808")

            async def set_my_commands(self, commands):
                return None

        session_factory = Mock()

        def make_session(*, proxy):
            fake_session = Mock()
            fake_session.proxy = proxy
            fake_session._connector_init = {}
            fake_session.close = AsyncMock()
            sessions.append(fake_session)
            return fake_session

        session_factory.side_effect = make_session
        fake_db = Mock()
        fake_db.init = AsyncMock()

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:abc"),
                patch.object(runtime, "AiohttpSession", session_factory),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", "socks5://127.0.0.1:10808"),
                patch.object(bot_module.dp, "start_polling", AsyncMock()),
            ):
                return await bot_module.start_bot()

        self.assertTrue(asyncio.run(run()))
        fake_db.init.assert_awaited_once()
        self.assertEqual([call.kwargs["proxy"] for call in session_factory.call_args_list], ["socks5://127.0.0.1:10808", None])
        self.assertTrue(all(session.close.await_count == 1 for session in sessions))
        self.assertIsNone(bot_module.bot)

    def test_connection_reset_error_calls_retry(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        class FakeBot:
            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                return None

            async def set_my_commands(self, commands):
                return None

        fake_session = Mock()
        fake_session._connector_init = {}
        fake_session.close = AsyncMock()
        fake_db = Mock()
        fake_db.init = AsyncMock()
        polling_calls = 0

        async def fake_polling(_bot):
            nonlocal polling_calls
            polling_calls += 1
            if polling_calls == 1:
                raise ConnectionResetError("WinError 64")
            return None

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:abc"),
                patch.object(runtime, "AiohttpSession", return_value=fake_session),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", ""),
                patch.object(bot_module.dp, "start_polling", side_effect=fake_polling),
                patch.object(runtime.asyncio, "sleep", AsyncMock()) as sleep_mock,
            ):
                return await bot_module.start_bot(), sleep_mock

        result, sleep_mock = asyncio.run(run())

        self.assertTrue(result)
        self.assertEqual(polling_calls, 2)
        sleep_mock.assert_awaited_once_with(1)
        self.assertEqual(fake_session.close.await_count, 2)

    def test_start_bot_handles_telegram_unauthorized_and_closes_session(self):
        import app.bot as bot_module
        import app.telegram_runtime as runtime

        class FakeBot:
            def __init__(self, token, session):
                self.token = token
                self.session = session

            async def delete_webhook(self, drop_pending_updates):
                raise TelegramUnauthorizedError(method=Mock(), message="Unauthorized")

        fake_session = Mock()
        fake_session._connector_init = {}
        fake_session.close = AsyncMock()
        fake_db = Mock()
        fake_db.init = AsyncMock()

        async def run():
            with (
                patch.object(runtime, "require_bot_token", return_value="123:bad"),
                patch.object(runtime, "AiohttpSession", return_value=fake_session),
                patch.object(runtime, "Bot", FakeBot),
                patch.object(bot_module, "db", fake_db),
                patch.object(runtime, "TELEGRAM_PROXY", ""),
            ):
                return await bot_module.start_bot()

        self.assertFalse(asyncio.run(run()))
        fake_db.init.assert_awaited_once()
        fake_session.close.assert_awaited_once()
        self.assertIsNone(bot_module.bot)
