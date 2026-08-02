import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

import app.ai_client as ai_client


class _FakeGeminiResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._body


class _FakeGeminiSession:
    def __init__(self, response: _FakeGeminiResponse | None = None, exc: Exception | None = None, *args, **kwargs):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        if self._exc is not None:
            outer_exc = self._exc

            class _RaisingContext:
                async def __aenter__(self):
                    raise outer_exc

                async def __aexit__(self, *args):
                    return False

            return _RaisingContext()
        return self._response


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

    async def test_gemini_http_429_returns_quota_message(self):
        body = (
            '{"error":{"code":429,"message":"Quota exceeded for metric: '
            'generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.0-flash",'
            '"status":"RESOURCE_EXHAUSTED"}}'
        )
        fake_logger = MagicMock()
        response = _FakeGeminiResponse(429, body)

        def client_session_factory(*args, response=response, **kwargs):
            return _FakeGeminiSession(response=response)

        with (
            patch.object(ai_client, "GEMINI_API_KEY", "gemini-secret"),
            patch.object(ai_client.aiohttp, "ClientSession", client_session_factory),
            patch.object(ai_client, "logger", fake_logger),
        ):
            result = await ai_client._ask_gemini("hello", system="system", max_tokens=10)

        self.assertIn("HTTP 429", result)
        self.assertIn("квот", result.lower())
        self.assertNotIn("TimeoutError", result)
        self.assertNotIn("gemini-secret", result)
        logged = " ".join(str(arg) for call in fake_logger.warning.call_args_list for arg in call.args)
        self.assertNotIn("gemini-secret", logged)

    async def test_gemini_timeout_error_stays_timeout(self):
        fake_logger = MagicMock()
        timeout_exc = TimeoutError("boom")

        def client_session_factory(*args, exc=timeout_exc, **kwargs):
            return _FakeGeminiSession(exc=exc)

        with (
            patch.object(ai_client, "GEMINI_API_KEY", "gemini-secret"),
            patch.object(ai_client.aiohttp, "ClientSession", client_session_factory),
            patch.object(ai_client, "logger", fake_logger),
        ):
            result = await ai_client._ask_gemini("hello", system="system", max_tokens=10)

        self.assertIn("timeout", result.lower())
        self.assertNotIn("HTTP 429", result)

    async def test_gemini_401_and_403_are_not_timeouts(self):
        cases = [
            (401, "AI error: Gemini API недоступен: проверьте API-ключ или права доступа (HTTP 401)"),
            (403, "AI error: Gemini API недоступен: проверьте API-ключ или права доступа (HTTP 403)"),
        ]
        for status, expected_prefix in cases:
            with self.subTest(status=status):
                body = f'{{"error":{{"code":{status},"message":"auth failed","status":"PERMISSION_DENIED"}}}}'
                response = _FakeGeminiResponse(status, body)

                def client_session_factory(*args, response=response, **kwargs):
                    return _FakeGeminiSession(response=response)

                with (
                    patch.object(ai_client, "GEMINI_API_KEY", "gemini-secret"),
                    patch.object(ai_client.aiohttp, "ClientSession", client_session_factory),
                ):
                    result = await ai_client._ask_gemini("hello", system="system", max_tokens=10)

                self.assertTrue(result.startswith(expected_prefix))
                self.assertNotIn("TimeoutError", result)
                self.assertNotIn("gemini-secret", result)

    async def test_gemini_404_and_500_are_classified_without_timeout(self):
        cases = [
            (404, "AI error: Gemini API недоступен: неверная модель или endpoint (HTTP 404)"),
            (500, "AI error: Gemini API временно недоступен (HTTP 500)"),
        ]
        for status, expected_prefix in cases:
            with self.subTest(status=status):
                body = f'{{"error":{{"code":{status},"message":"server error","status":"INTERNAL"}}}}'
                response = _FakeGeminiResponse(status, body)

                def client_session_factory(*args, response=response, **kwargs):
                    return _FakeGeminiSession(response=response)

                with (
                    patch.object(ai_client, "GEMINI_API_KEY", "gemini-secret"),
                    patch.object(ai_client.aiohttp, "ClientSession", client_session_factory),
                ):
                    result = await ai_client._ask_gemini("hello", system="system", max_tokens=10)

                self.assertTrue(result.startswith(expected_prefix))
                self.assertNotIn("TimeoutError", result)
                self.assertNotIn("gemini-secret", result)


class AiohttpTimeoutCompatTests(unittest.TestCase):
    """Verify timeout classification against installed aiohttp 3.9.5."""

    def test_connection_timeout_compatibility(self):
        # aiohttp 3.9 lacks ConnectionTimeoutError, newer versions may expose it.
        # Production code must remain compatible with both API shapes.
        exc_type = getattr(aiohttp, "ConnectionTimeoutError", aiohttp.ServerTimeoutError)
        self.assertTrue(issubclass(exc_type, TimeoutError))

    def test_server_timeout_error_is_timeout_error_subclass(self):
        self.assertTrue(issubclass(aiohttp.ServerTimeoutError, TimeoutError))

    def test_gemini_timeout_message_for_server_timeout(self):
        exc = aiohttp.ServerTimeoutError("read timeout")
        msg = ai_client._gemini_timeout_message(exc)
        self.assertEqual(msg, "AI error: Gemini read timeout")
        self.assertNotIn("TimeoutError", msg)

    def test_gemini_timeout_message_for_plain_timeout(self):
        exc = TimeoutError("generic timeout")
        msg = ai_client._gemini_timeout_message(exc)
        self.assertEqual(msg, "AI error: Gemini request timeout")
        self.assertNotIn("HTTP 429", msg)

    def test_gemini_exception_message_for_server_timeout(self):
        exc = aiohttp.ServerTimeoutError("read timeout")
        msg = ai_client._gemini_exception_message(exc)
        self.assertEqual(msg, "AI error: Gemini read timeout")

    def test_gemini_exception_message_for_client_connector_error(self):
        os_err = OSError(2, "No such file or directory")
        exc = aiohttp.ClientConnectorError(
            connection_key=MagicMock(host="generativelanguage.googleapis.com"),
            os_error=os_err,
        )
        msg = ai_client._gemini_exception_message(exc)
        self.assertEqual(msg, "AI error: Gemini connection error")
        self.assertNotIn("TimeoutError", msg)

    def test_gemini_exception_message_for_ssl_error(self):
        import ssl as _ssl
        exc = _ssl.SSLError("certificate verify failed")
        msg = ai_client._gemini_exception_message(exc)
        self.assertEqual(msg, "AI error: Gemini SSL/TLS error")
        self.assertNotIn("TimeoutError", msg)

    def test_gemini_exception_message_falls_back_to_type_name(self):
        exc = ValueError("something unexpected")
        msg = ai_client._gemini_exception_message(exc)
        self.assertIn("ValueError", msg)
        self.assertIn("something unexpected", msg)

    def test_gemini_exception_message_empty_str_fallback(self):
        exc = RuntimeError()
        msg = ai_client._gemini_exception_message(exc)
        self.assertIn("RuntimeError", msg)
        self.assertNotIn("None", msg)


class RetryAfterHeaderTests(unittest.TestCase):
    """Verify Retry-After header extraction from Gemini 429 responses."""

    def test_429_with_retry_after_logs_retry_delay(self):
        fake_logger = MagicMock()
        body = '{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}'

        class _FakeResp:
            status = 429
            headers = {"Retry-After": "30"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def text(self):
                return body

        with (
            patch.object(ai_client, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_client, "logger", fake_logger),
        ):
            result = ai_client._gemini_http_error_message(429, {"error": {"message": "Quota exceeded"}}, body, _FakeResp())

        self.assertIn("HTTP 429", result)
        self.assertIn("квот", result.lower())
        self.assertNotIn("TimeoutError", result)
        logged = " ".join(str(arg) for call in fake_logger.warning.call_args_list for arg in call.args)
        self.assertIn("retry_after=30", logged)

    def test_429_without_retry_after_no_retry_field(self):
        fake_logger = MagicMock()
        body = '{"error":{"code":429,"message":"Quota exceeded"}}'

        class _FakeResp:
            status = 429
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def text(self):
                return body

        with (
            patch.object(ai_client, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_client, "logger", fake_logger),
        ):
            result = ai_client._gemini_http_error_message(429, {"error": {"message": "Quota exceeded"}}, body, _FakeResp())

        self.assertIn("HTTP 429", result)
        logged = " ".join(str(arg) for call in fake_logger.warning.call_args_list for arg in call.args)
        self.assertNotIn("retry_after", logged)

    def test_safe_body_snippet_redacts_api_key(self):
        with patch.object(ai_client, "GEMINI_API_KEY", "AIzaSy-test-key-here"):
            snippet = ai_client._safe_body_snippet("key=AIzaSy-test-key-here rest", limit=100)
        self.assertNotIn("AIzaSy-test-key-here", snippet)
        self.assertIn("<redacted>", snippet)

    def test_safe_body_snippet_truncates(self):
        long_text = "x" * 1000
        snippet = ai_client._safe_body_snippet(long_text, limit=100)
        self.assertEqual(len(snippet), 100)

    def test_http_error_message_no_resp_fallback(self):
        result = ai_client._gemini_http_error_message(429, {"error": {"message": "Quota exceeded"}}, "body", None)
        self.assertIn("HTTP 429", result)
        self.assertIn("квот", result.lower())
