"""SSRF regression tests for importer image metadata fetching."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from app.importers.image_fetcher import (
    _SafeSourceRedirectHandler,
    _is_allowed_source_url,
    resolve_image_url_from_source,
)


class AllowedSourceUrlTests(unittest.TestCase):
    def test_accepts_supported_marketplace_hosts(self):
        for url in (
            "https://ozon.ru/product/1",
            "https://www.ozon.ru/product/1",
            "https://market.yandex.ru/card/1",
            "https://www.wildberries.ru/catalog/1",
            "https://funpay.com/lots/offer?id=1",
        ):
            with self.subTest(url=url):
                self.assertTrue(_is_allowed_source_url(url))

    def test_rejects_private_and_local_addresses(self):
        for url in (
            "http://127.0.0.1:8000/admin",
            "http://localhost:5432/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
        ):
            with self.subTest(url=url):
                self.assertFalse(_is_allowed_source_url(url))

    def test_rejects_lookalike_hosts_and_credentials(self):
        for url in (
            "https://ozon.ru.evil.example/product/1",
            "https://notozon.ru/product/1",
            "https://ozon.ru@127.0.0.1/admin",
            "https://user:pass@ozon.ru/product/1",
            "https://ozon.ru:8443/product/1",
            "file:///etc/passwd",
            "ftp://ozon.ru/file",
        ):
            with self.subTest(url=url):
                self.assertFalse(_is_allowed_source_url(url))

    def test_invalid_port_is_rejected_without_exception(self):
        self.assertFalse(_is_allowed_source_url("https://ozon.ru:invalid/product/1"))

    def test_disallowed_source_is_rejected_before_network_fetch(self):
        with patch("app.importers.image_fetcher._resolve_image_url_cached") as fetch:
            self.assertIsNone(resolve_image_url_from_source("http://127.0.0.1/admin"))
        fetch.assert_not_called()


class SafeRedirectHandlerTests(unittest.TestCase):
    def test_rejects_redirect_to_private_address(self):
        handler = _SafeSourceRedirectHandler()
        request = Request("https://ozon.ru/product/1")
        result = handler.redirect_request(
            request, None, 302, "Found", {}, "http://127.0.0.1:8000/admin"
        )
        self.assertIsNone(result)

    def test_rejects_redirect_to_untrusted_public_host(self):
        handler = _SafeSourceRedirectHandler()
        request = Request("https://ozon.ru/product/1")
        result = handler.redirect_request(
            request, None, 302, "Found", {}, "https://attacker.example/"
        )
        self.assertIsNone(result)

    def test_allows_redirect_between_supported_marketplaces(self):
        handler = _SafeSourceRedirectHandler()
        request = Request("https://ozon.ru/product/1")
        result = handler.redirect_request(
            request, None, 302, "Found", {}, "https://www.ozon.ru/product/1"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.full_url, "https://www.ozon.ru/product/1")


if __name__ == "__main__":
    unittest.main()
