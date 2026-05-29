import re
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import _normalize_proxy


class ConfigTests(unittest.TestCase):
    def test_env_example_does_not_contain_telegram_bot_token(self):
        env_example = Path(__file__).resolve().parent.parent / ".env.example"
        text = env_example.read_text(encoding="utf-8")

        self.assertNotRegex(text, re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"))

    def test_normalize_proxy_ignores_placeholder(self):
        self.assertEqual(_normalize_proxy("http://user:pass@ip:port"), "")

    def test_normalize_proxy_ignores_malformed_values(self):
        self.assertEqual(_normalize_proxy("not-a-url"), "")
        self.assertEqual(_normalize_proxy("http://127.0.0.1"), "")
        self.assertEqual(_normalize_proxy("http://user:pass@127.0.0.1:port"), "")

    def test_normalize_proxy_keeps_real_proxy(self):
        self.assertEqual(
            _normalize_proxy("http://user:pass@127.0.0.1:8080"),
            "http://user:pass@127.0.0.1:8080",
        )

    def test_config_proxy_ignores_placeholder_env(self):
        with patch.dict("os.environ", {"PROXY": "http://user:pass@ip:port"}):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.PROXY, "")
        self.assertEqual(config.PARSER_PROXY, "")
        self.assertEqual(config.COMMON_PROXY, "")

    def test_legacy_proxy_is_parser_only_not_telegram(self):
        with patch.dict(
            "os.environ",
            {
                "PROXY": "http://user:pass@127.0.0.1:8080",
                "COMMON_PROXY": "",
                "PARSER_PROXY": "",
                "TELEGRAM_API_PROXY": "",
                "TELEGRAM_PROXY": "",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.PARSER_PROXY, "http://user:pass@127.0.0.1:8080")
        self.assertEqual(config.PROXY, "http://user:pass@127.0.0.1:8080")
        self.assertEqual(config.TELEGRAM_PROXY, "")

    def test_telegram_proxy_prefers_specific_env(self):
        with patch.dict(
            "os.environ",
            {
                "PROXY": "http://user:pass@127.0.0.1:8080",
                "TELEGRAM_API_PROXY": "",
                "TELEGRAM_PROXY": "socks5://user:pass@127.0.0.1:1080",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.TELEGRAM_PROXY, "socks5://user:pass@127.0.0.1:1080")

    def test_telegram_proxy_prefers_api_proxy_alias(self):
        with patch.dict(
            "os.environ",
            {
                "PROXY": "http://user:pass@127.0.0.1:8080",
                "TELEGRAM_API_PROXY": "socks5://127.0.0.1:1080",
                "TELEGRAM_PROXY": "socks5://127.0.0.1:1081",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.TELEGRAM_PROXY, "socks5://127.0.0.1:1080")

    def test_parser_proxy_prefers_parser_proxy_over_common_proxy(self):
        with patch.dict(
            "os.environ",
            {
                "PARSER_PROXY": "http://user:pass@127.0.0.1:8082",
                "COMMON_PROXY": "http://user:pass@127.0.0.1:8080",
                "TELEGRAM_API_PROXY": "",
                "TELEGRAM_PROXY": "",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.PARSER_PROXY, "http://user:pass@127.0.0.1:8082")
        self.assertEqual(config.PROXY, "http://user:pass@127.0.0.1:8082")

    def test_telegram_proxy_falls_back_to_common_proxy(self):
        with patch.dict(
            "os.environ",
            {
                "COMMON_PROXY": "http://user:pass@127.0.0.1:8080",
                "PARSER_PROXY": "",
                "PROXY": "",
                "TELEGRAM_API_PROXY": "",
                "TELEGRAM_PROXY": "",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.TELEGRAM_PROXY, "http://user:pass@127.0.0.1:8080")

    def test_telegram_proxy_does_not_fall_back_to_standard_proxy_env(self):
        with patch.dict(
            "os.environ",
            {
                "PROXY": "",
                "COMMON_PROXY": "",
                "TELEGRAM_API_PROXY": "",
                "TELEGRAM_PROXY": "",
                "HTTPS_PROXY": "http://user:pass@127.0.0.1:8081",
                "HTTP_PROXY": "",
                "ALL_PROXY": "",
            },
        ):
            import importlib
            import app.config

            config = importlib.reload(app.config)

        self.assertEqual(config.COMMON_PROXY, "")
        self.assertEqual(config.TELEGRAM_PROXY, "")
