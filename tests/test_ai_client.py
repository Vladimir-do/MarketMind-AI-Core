import unittest
from unittest.mock import AsyncMock, patch

import app.ai_client as ai_client


class AiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_grok_key_reports_configuration_error(self):
        with patch.object(ai_client, "AI_PROVIDER", "grok"), patch.object(ai_client, "GROK_API_KEY", ""):
            self.assertFalse(ai_client.ai_is_available())
            self.assertIn("GROK_API_KEY", ai_client.ai_missing_message())

    async def test_ask_ai_routes_to_grok(self):
        with (
            patch.object(ai_client, "AI_PROVIDER", "grok"),
            patch.object(ai_client, "GROK_API_KEY", "xai-test"),
            patch.object(ai_client, "_ask_grok", new=AsyncMock(return_value="ok")) as ask_grok,
        ):
            result = await ai_client.ask_ai("hello")
        self.assertEqual(result, "ok")
        ask_grok.assert_awaited_once()

    async def test_ask_ai_routes_to_claude(self):
        with (
            patch.object(ai_client, "AI_PROVIDER", "claude"),
            patch.object(ai_client, "ANTHROPIC_API_KEY", "sk-test"),
            patch.object(ai_client, "_ask_claude", new=AsyncMock(return_value="ok")) as ask_claude,
        ):
            result = await ai_client.ask_ai("hello")
        self.assertEqual(result, "ok")
        ask_claude.assert_awaited_once()

    async def test_grok_string_error_payload_does_not_crash(self):
        class FakeResponse:
            status = 400

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def json(self, content_type=None):
                return {"error": "bad request"}

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return FakeResponse()

        with (
            patch.object(ai_client, "GROK_API_KEY", "xai-test"),
            patch.object(ai_client.aiohttp, "ClientSession", FakeSession),
        ):
            result = await ai_client._ask_grok("hello", system="system", max_tokens=10)

        self.assertEqual(result, "AI error: bad request")
