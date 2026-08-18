"""Regression tests for BLOCKER SEC-SSRF-1 (Verification Report).

Marketplace-domain checks used to be plain substring matches (e.g.
``"ozon.ru" in host``), which also match attacker-controlled hosts like
``ozon.ru.evil.com`` or ``notfunpay.com``. Such a URL would be classified as
a trusted marketplace URL and routed to a real network fetch / browser
navigation against an arbitrary host (SSRF).

These tests pin the fix: only an exact host or a proper subdomain of the
known marketplace hosts must be accepted.
"""

import unittest

from app.parsers.funpay import is_funpay_offer_url
from app.parsers.router import detect_marketplace
from app.telegram_url_utils import is_supported_marketplace_url
from app.utils.urls import is_ozon_url, is_wildberries_url, is_yandex_market_url


class UrlUtilsDomainMatchingTests(unittest.TestCase):
    def test_ozon_accepts_exact_and_subdomain_hosts(self):
        self.assertTrue(is_ozon_url("https://ozon.ru/product/123"))
        self.assertTrue(is_ozon_url("https://www.ozon.ru/product/123"))

    def test_ozon_rejects_lookalike_host(self):
        self.assertFalse(is_ozon_url("https://ozon.ru.evil.com/product/123"))
        self.assertFalse(is_ozon_url("https://notozon.ru/product/123"))

    def test_wildberries_accepts_exact_and_subdomain_hosts(self):
        self.assertTrue(is_wildberries_url("https://www.wildberries.ru/catalog/1/detail.aspx"))
        self.assertTrue(is_wildberries_url("https://www.wb.ru/catalog/1"))

    def test_wildberries_rejects_lookalike_host(self):
        self.assertFalse(is_wildberries_url("https://wildberries.ru.evil.com/catalog/1"))
        self.assertFalse(is_wildberries_url("https://showwb.ru/catalog/1"))

    def test_yandex_market_rejects_lookalike_host(self):
        self.assertFalse(is_yandex_market_url("https://market.yandex.ru.evil.com/product/1"))


class DetectMarketplaceSsrfTests(unittest.TestCase):
    def test_lookalike_ozon_host_is_not_routed_to_ozon(self):
        self.assertEqual(detect_marketplace("https://ozon.ru.evil.com/product/123"), "unknown")

    def test_lookalike_wildberries_host_is_not_routed_to_wildberries(self):
        self.assertEqual(detect_marketplace("https://wb.ru.evil.com/catalog/123"), "unknown")

    def test_real_hosts_still_detected(self):
        self.assertEqual(detect_marketplace("https://www.ozon.ru/product/123"), "ozon")
        self.assertEqual(detect_marketplace("https://www.wildberries.ru/catalog/123/detail.aspx"), "wildberries")


class TelegramSupportedMarketplaceUrlSsrfTests(unittest.TestCase):
    def test_lookalike_ozon_product_url_is_not_supported(self):
        self.assertFalse(is_supported_marketplace_url("https://ozon.ru.evil.com/product/123"))

    def test_real_ozon_product_url_still_supported(self):
        self.assertTrue(is_supported_marketplace_url("https://www.ozon.ru/product/123"))


class FunPayOfferUrlSsrfTests(unittest.TestCase):
    def test_lookalike_funpay_host_is_rejected(self):
        self.assertFalse(is_funpay_offer_url("https://notfunpay.com/lots/offer?id=1"))

    def test_real_funpay_host_still_accepted(self):
        self.assertTrue(is_funpay_offer_url("https://funpay.com/lots/offer?id=68683803"))
        self.assertTrue(is_funpay_offer_url("https://www.funpay.com/lots/offer?id=68683803"))


if __name__ == "__main__":
    unittest.main()
