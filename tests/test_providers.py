"""Tests for the real AI provider implementations."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai_recommendation.providers.factory import (
    ProviderType,
    create_configured_provider,
    create_provider,
)
from app.ai_recommendation.providers.fallback import FallbackAIProvider
from app.ai_recommendation.providers.ollama_provider import OllamaProvider
from app.ai_recommendation.providers.openai_compatible import OpenAICompatibleProvider


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_ollama_response(content: str = "Hello") -> dict:
    return {"message": {"content": content}, "model": "llama3", "eval_count": 10}


def _mock_openai_response(content: str = "Hello", model: str = "gpt-4o-mini") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }


def _make_async_response(body: dict, status: int = 200) -> MagicMock:
    """Create a mock response that works as async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body)

    ctx_resp = AsyncMock()
    ctx_resp.__aenter__ = AsyncMock(return_value=resp)
    ctx_resp.__aexit__ = AsyncMock(return_value=False)
    return ctx_resp


def _make_session_mock(post_response: MagicMock) -> MagicMock:
    """Create a mock aiohttp.ClientSession with async context manager support."""
    session = MagicMock()
    session.post = MagicMock(return_value=post_response)

    ctx_session = MagicMock()
    ctx_session.__aenter__ = AsyncMock(return_value=session)
    ctx_session.__aexit__ = AsyncMock(return_value=False)
    return ctx_session


class TestOpenAICompatibleProvider(unittest.TestCase):
    def test_is_available_with_key_and_url(self):
        p = OpenAICompatibleProvider(api_key="sk-test", model="gpt-4o-mini", provider_label="openai")
        self.assertTrue(p.is_available())

    def test_unavailable_no_key(self):
        p = OpenAICompatibleProvider(api_key="", provider_label="openai")
        self.assertFalse(p.is_available())

    def test_unavailable_no_url(self):
        p = OpenAICompatibleProvider(api_key="sk-test", base_url="custom", model="x")
        self.assertTrue(p.is_available())

    def test_name(self):
        p = OpenAICompatibleProvider(api_key="k", provider_label="deepseek")
        self.assertEqual(p.name(), "deepseek")

    def test_complete_success(self):
        p = OpenAICompatibleProvider(api_key="sk-test", provider_label="openai")

        post_resp = _make_async_response(_mock_openai_response("test output"))
        session_mock = _make_session_mock(post_resp)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession.return_value = session_mock
        mock_aiohttp.ClientTimeout.return_value = MagicMock()

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            result = _run(p.complete("say hello", system="be brief"))

        self.assertEqual(result.text, "test output")
        self.assertEqual(result.model, "gpt-4o-mini")
        self.assertEqual(result.input_tokens, 5)
        self.assertEqual(result.output_tokens, 3)

    def test_complete_http_error(self):
        p = OpenAICompatibleProvider(api_key="sk-test", provider_label="openai")

        post_resp = _make_async_response({"error": {"message": "Unauthorized"}}, status=401)
        session_mock = _make_session_mock(post_resp)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession.return_value = session_mock
        mock_aiohttp.ClientTimeout.return_value = MagicMock()

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            result = _run(p.complete("test"))

        self.assertEqual(result.text, "")

    def test_default_base_urls(self):
        p = OpenAICompatibleProvider(api_key="k", provider_label="deepseek")
        self.assertEqual(p._base_url, "https://api.deepseek.com/v1")

        p2 = OpenAICompatibleProvider(api_key="k", provider_label="mimo")
        self.assertEqual(p2._base_url, "https://api.mimo.ai/v1")


class TestOllamaProvider(unittest.TestCase):
    def test_is_available(self):
        p = OllamaProvider()
        self.assertTrue(p.is_available())

    def test_name(self):
        self.assertEqual(OllamaProvider().name(), "ollama")

    def test_default_base_url(self):
        p = OllamaProvider()
        self.assertEqual(p._base_url, "http://localhost:11434")

    def test_custom_base_url(self):
        p = OllamaProvider(base_url="http://myhost:9999")
        self.assertEqual(p._base_url, "http://myhost:9999")

    def test_complete_success(self):
        p = OllamaProvider(model="llama3")

        post_resp = _make_async_response(_mock_ollama_response("pong"))
        session_mock = _make_session_mock(post_resp)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession.return_value = session_mock
        mock_aiohttp.ClientTimeout.return_value = MagicMock()

        with patch("app.ai_recommendation.providers.ollama_provider.aiohttp", mock_aiohttp):
            result = _run(p.complete("ping"))

        self.assertEqual(result.text, "pong")
        self.assertEqual(result.model, "llama3")

    def test_complete_error(self):
        p = OllamaProvider()

        post_resp = _make_async_response({"error": "model not found"}, status=500)
        session_mock = _make_session_mock(post_resp)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession.return_value = session_mock
        mock_aiohttp.ClientTimeout.return_value = MagicMock()

        with patch("app.ai_recommendation.providers.ollama_provider.aiohttp", mock_aiohttp):
            result = _run(p.complete("test"))

        self.assertEqual(result.text, "")


class TestFactory(unittest.TestCase):
    @patch.dict("os.environ", {"AI_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "sk-ds"})
    def test_create_configured_provider_deepseek(self):
        p = create_configured_provider()
        self.assertIsInstance(p, OpenAICompatibleProvider)
        self.assertEqual(p.name(), "deepseek")

    @patch.dict("os.environ", {"AI_PROVIDER": "ollama"})
    def test_create_configured_provider_ollama(self):
        p = create_configured_provider()
        self.assertIsInstance(p, OllamaProvider)

    def test_create_provider_explicit(self):
        p = create_provider(ProviderType.ollama)
        self.assertIsInstance(p, OllamaProvider)

    def test_create_provider_openai(self):
        p = create_provider(ProviderType.openai, api_key="sk-test")
        self.assertIsInstance(p, OpenAICompatibleProvider)
        self.assertEqual(p.name(), "openai")

    @patch.dict("os.environ", {"AI_PROVIDER": "bogus"})
    def test_unknown_provider_falls_back_to_ollama(self):
        p = create_configured_provider()
        self.assertIsInstance(p, OllamaProvider)

    @patch.dict("os.environ", {"AI_PROVIDER": "ollama", "OLLAMA_MODEL": "mistral"})
    def test_create_configured_provider_uses_model_env(self):
        p = create_configured_provider()
        self.assertEqual(p._model, "mistral")

    @patch.dict("os.environ", {"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test"})
    def test_create_configured_provider_claude_is_available(self):
        """Regression test: ProviderType.claude previously had no base_url in
        _PROVIDER_BASE_URLS, so is_available() was always False even with a
        valid ANTHROPIC_API_KEY."""
        p = create_configured_provider()
        self.assertIsInstance(p, OpenAICompatibleProvider)
        self.assertEqual(p.name(), "claude")
        self.assertTrue(p.is_available(), "claude provider must be available with a valid API key")
        self.assertTrue(p.base_url, "claude provider must resolve a non-empty base_url")

    def test_create_configured_provider_default_matches_config_ai_provider_default(self):
        """When AI_PROVIDER is unset, the factory's hardcoded default must
        match app.config.AI_PROVIDER's hardcoded default ("grok"), not
        silently diverge to "ollama". (app.config.AI_PROVIDER itself is read
        from the environment/.env at import time and may not equal its own
        source default in a configured deployment, so this asserts against
        the literal both modules are meant to agree on, not the live value.)"""
        import inspect

        import app.config as config_module

        source = inspect.getsource(config_module)
        self.assertIn(
            'os.getenv("AI_PROVIDER", "grok")', source,
            "app.config.AI_PROVIDER's own default changed -- update this test "
            "and factory.py's default together",
        )

        original = os.environ.pop("AI_PROVIDER", None)
        try:
            with patch.dict("os.environ", {"GROK_API_KEY": "xai-test"}):
                p = create_configured_provider()
            self.assertEqual(p.name(), "grok")
        finally:
            if original is not None:
                os.environ["AI_PROVIDER"] = original


def _build_fallback_mock(responses: list[tuple[int, dict]]):
    """Build a mock aiohttp module that returns responses in order.

    responses is a list of (status, body_dict) tuples.
    """
    call_idx = [0]

    def make_session(timeout=None):
        idx = call_idx[0]
        call_idx[0] += 1
        status, body = responses[min(idx, len(responses) - 1)]
        post_resp = _make_async_response(body, status=status)
        return _make_session_mock(post_resp)

    mock_aiohttp = MagicMock()
    mock_aiohttp.ClientSession = MagicMock(side_effect=make_session)
    mock_aiohttp.ClientTimeout.return_value = MagicMock()
    return mock_aiohttp


class TestFallbackProvider(unittest.TestCase):
    def test_tries_next_on_error(self):
        bad = OpenAICompatibleProvider(api_key="sk-bad", provider_label="openai")
        good = OpenAICompatibleProvider(api_key="sk-good", provider_label="deepseek")

        mock_aiohttp = _build_fallback_mock([
            (500, {"error": {"message": "Server error"}}),
            (200, _mock_openai_response("fallback works")),
        ])

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            fb = FallbackAIProvider([bad, good])
            result = _run(fb.complete("test"))

        self.assertEqual(result.text, "fallback works")

    def test_returns_first_success(self):
        fast = OpenAICompatibleProvider(api_key="sk-fast", provider_label="openai")
        slow = OpenAICompatibleProvider(api_key="sk-slow", provider_label="deepseek")

        mock_aiohttp = _build_fallback_mock([
            (200, _mock_openai_response("first wins")),
        ])

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            fb = FallbackAIProvider([fast, slow])
            result = _run(fb.complete("test"))

        self.assertEqual(result.text, "first wins")

    def test_all_fail_raises(self):
        bad1 = OpenAICompatibleProvider(api_key="sk-1", provider_label="openai")
        bad2 = OpenAICompatibleProvider(api_key="sk-2", provider_label="deepseek")

        mock_aiohttp = _build_fallback_mock([
            (500, {"error": {"message": "fail"}}),
            (500, {"error": {"message": "fail"}}),
        ])

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            fb = FallbackAIProvider([bad1, bad2])
            result = _run(fb.complete("test"))

        self.assertEqual(result.text, "")

    def test_is_available_if_any_available(self):
        unavailable = OpenAICompatibleProvider(api_key="", provider_label="openai")
        available = OllamaProvider()
        fb = FallbackAIProvider([unavailable, available])
        self.assertTrue(fb.is_available())

    def test_is_available_none(self):
        unavailable = OpenAICompatibleProvider(api_key="", provider_label="openai")
        fb = FallbackAIProvider([unavailable])
        self.assertFalse(fb.is_available())

    def test_name_shows_available(self):
        available = OllamaProvider()
        fb = FallbackAIProvider([available])
        self.assertIn("ollama", fb.name())

    def test_skips_unavailable_providers(self):
        unavailable = OpenAICompatibleProvider(api_key="", provider_label="openai")
        available = OllamaProvider()

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientTimeout.return_value = MagicMock()

        post_resp = _make_async_response(_mock_ollama_response("from ollama"))
        session_mock = _make_session_mock(post_resp)
        mock_aiohttp.ClientSession.return_value = session_mock

        with patch("app.ai_recommendation.providers.ollama_provider.aiohttp", mock_aiohttp):
            fb = FallbackAIProvider([unavailable, available])
            result = _run(fb.complete("test"))

        self.assertEqual(result.text, "from ollama")

    def test_empty_response_tries_next(self):
        p1 = OpenAICompatibleProvider(api_key="sk-1", provider_label="openai")
        p2 = OllamaProvider()

        mock_aiohttp = _build_fallback_mock([
            (200, _mock_openai_response("")),
            (200, _mock_ollama_response("second")),
        ])

        with patch("app.ai_recommendation.providers.openai_compatible.aiohttp", mock_aiohttp):
            with patch("app.ai_recommendation.providers.ollama_provider.aiohttp", mock_aiohttp):
                fb = FallbackAIProvider([p1, p2])
                result = _run(fb.complete("test"))

        self.assertEqual(result.text, "second")


if __name__ == "__main__":
    unittest.main()
