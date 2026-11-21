"""Regression tests for strict product source URL validation."""

import unittest

from app.products.schema import UnifiedProduct
from app.products.validator import ProductValidator


class ProductSourceUrlValidationTests(unittest.TestCase):
    def make_product(self, url):
        return UnifiedProduct(
            name="Test product",
            source_id="test-1",
            source_type="test",
            source_url=url,
        )

    def test_accepts_http_and_https_urls(self):
        for url in ("https://example.com/item/1", "http://example.com:8080/item"):
            with self.subTest(url=url):
                valid, errors = ProductValidator().validate([self.make_product(url)])
                self.assertEqual(len(valid), 1)
                self.assertFalse(any(e.rule == "url_valid" for e in errors))

    def test_rejects_non_http_schemes(self):
        for url in ("ftp://example.com/file", "javascript:alert(1)", "file:///tmp/file"):
            with self.subTest(url=url):
                valid, errors = ProductValidator().validate([self.make_product(url)])
                self.assertEqual(len(valid), 0)
                self.assertTrue(any(e.rule == "url_valid" for e in errors))

    def test_rejects_urls_without_host(self):
        for url in ("https:///missing-host", "https://", "/relative/path"):
            with self.subTest(url=url):
                valid, errors = ProductValidator().validate([self.make_product(url)])
                self.assertEqual(len(valid), 0)
                self.assertTrue(any(e.rule == "url_valid" for e in errors))

    def test_rejects_embedded_credentials(self):
        for url in ("https://user:pass@example.com/item", "https://user@example.com"):
            with self.subTest(url=url):
                valid, errors = ProductValidator().validate([self.make_product(url)])
                self.assertEqual(len(valid), 0)
                self.assertTrue(any(e.rule == "url_valid" for e in errors))

    def test_rejects_malformed_ports_and_whitespace(self):
        for url in ("https://example.com:99999/item", "https://example.com/item with spaces"):
            with self.subTest(url=url):
                valid, errors = ProductValidator().validate([self.make_product(url)])
                self.assertEqual(len(valid), 0)
                self.assertTrue(any(e.rule == "url_valid" for e in errors))

    def test_empty_source_url_is_optional(self):
        valid, errors = ProductValidator().validate([self.make_product(None)])
        self.assertEqual(len(valid), 1)
        self.assertFalse(any(e.rule == "url_valid" for e in errors))


if __name__ == "__main__":
    unittest.main()
