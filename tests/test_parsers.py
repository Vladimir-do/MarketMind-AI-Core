import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.parsers.base import ProductData
from app.parsers.router import detect_marketplace
from app.parsers.wildberries import (
    WildberriesParser,
    _build_wb_image_url,
    _extract_wb_id,
    _get_basket_host,
    _wbbasket_candidates,
)
from app.parsers.yandex_market import YandexMarketParser, parse_yandex_market_html
from app.searcher import _parse_search_results
from app.updater import (
    OzonUpdater,
    _extract_ozon_incident_id,
    parse_ozon_api_json,
    parse_ozon_html,
)


class ParserTests(unittest.TestCase):
    def test_detect_marketplace(self):
        self.assertEqual(detect_marketplace("https://www.ozon.ru/product/123"), "ozon")
        self.assertEqual(
            detect_marketplace("https://www.wildberries.ru/catalog/123/detail.aspx"),
            "wildberries",
        )
        self.assertEqual(detect_marketplace("https://www.wb.ru/catalog/123"), "wildberries")
        self.assertEqual(detect_marketplace("https://market.yandex.ru/product--phone/123"), "yandex_market")
        self.assertEqual(detect_marketplace("https://example.com"), "unknown")

    def test_yandex_market_html_parser_json_ld(self):
        html = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Смартфон Example 128 ГБ",
              "image": ["https://avatars.mds.yandex.net/get-mpic/test/orig"],
              "brand": {"@type": "Brand", "name": "Example"},
              "aggregateRating": {"ratingValue": "4.7", "reviewCount": "153"},
              "offers": {
                "@type": "Offer",
                "price": "12990",
                "priceCurrency": "RUB",
                "availability": "https://schema.org/InStock"
              }
            }
            </script>
          </head>
          <body><h1>Fallback</h1></body>
        </html>
        """
        data = parse_yandex_market_html(html, "https://market.yandex.ru/product--phone/123")

        self.assertIsInstance(data, ProductData)
        self.assertEqual(data.name, "Смартфон Example 128 ГБ")
        self.assertEqual(data.price, 12990)
        self.assertEqual(data.availability, "in_stock")
        self.assertEqual(data.image_url, "https://avatars.mds.yandex.net/get-mpic/test/orig")
        self.assertEqual(data.rating, 4.7)
        self.assertEqual(data.reviews_count, 153)
        self.assertEqual(data.brand, "Example")
        self.assertEqual(data.marketplace, "yandex_market")

    def test_yandex_market_attempt_recorder_gets_normalized_fields(self):
        attempts = []

        async def recorder(**kwargs):
            attempts.append(kwargs)

        parser = YandexMarketParser(attempt_recorder=recorder)
        asyncio.run(
            parser._record_attempt(
                url="https://market.yandex.ru/product--phone/123",
                source="html",
                status="blocked",
                http_status=403,
                latency_ms=42,
            )
        )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["marketplace"], "yandex_market")
        self.assertEqual(attempts[0]["source"], "html")
        self.assertEqual(attempts[0]["status"], "blocked")
        self.assertEqual(attempts[0]["http_status"], 403)
        self.assertEqual(attempts[0]["latency_ms"], 42)

    def test_extract_wb_id_variants(self):
        self.assertEqual(_extract_wb_id("https://www.wildberries.ru/catalog/311895731/detail.aspx"), 311895731)
        self.assertEqual(_extract_wb_id("https://www.wb.ru/catalog/311895731?targetUrl=XS"), 311895731)
        self.assertEqual(_extract_wb_id("https://example.com/?nm=311895731"), 311895731)
        self.assertEqual(_extract_wb_id("757984979"), 757984979)
        self.assertEqual(
            _extract_wb_id("https://www.wildberries.ru/catalog/757984979/detail.aspx?size=123456789"),
            757984979,
        )
        self.assertIsNone(_extract_wb_id("https://example.com/no-id"))

    def test_wildberries_parse_product(self):
        raw = {
            "name": "Headphones",
            "brand": "Acme",
            "sizes": [
                {
                    "price": {"product": 129900, "basic": 199900},
                    "stocks": [{"qty": 3}],
                }
            ],
            "reviewRating": 4.7,
            "feedbacks": 42,
        }
        data = WildberriesParser()._parse_product(
            raw,
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            311895731,
            session=None,
        )
        self.assertIsInstance(data, ProductData)
        self.assertEqual(data.name, "Acme Headphones")
        self.assertEqual(data.price, 1299)
        self.assertEqual(data.old_price, 1999)
        self.assertEqual(data.availability, "in_stock")
        self.assertEqual(data.marketplace, "wildberries")

    def test_wb_search_parses_old_price_and_discount(self):
        parser = WildberriesParser()
        payload = {
            "data": {
                "products": [
                    {
                        "id": 757984979,
                        "name": "Игровое кресло",
                        "brand": "Brand",
                        "reviewRating": 4.8,
                        "feedbacks": 10,
                        "sizes": [
                            {
                                "price": {"product": 750000, "basic": 1200000},
                                "stocks": [{"qty": 2}],
                            }
                        ],
                    }
                ]
            }
        }

        class FakeResp:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def text(self):
                import json
                return json.dumps(payload, ensure_ascii=False)

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def get(self, *args, **kwargs):
                return FakeResp()

        with patch("aiohttp.ClientSession", FakeSession):
            results = asyncio.run(parser.search("игровое кресло", max_results=5))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].price, 7500)
        self.assertEqual(results[0].old_price, 12000)
        self.assertEqual(results[0].discount_pct, 38)
        self.assertEqual(results[0].availability, "in_stock")

    def test_wildberries_attempt_recorder_gets_normalized_fields(self):
        attempts = []

        async def recorder(**kwargs):
            attempts.append(kwargs)

        parser = WildberriesParser(attempt_recorder=recorder)
        asyncio.run(
            parser._record_attempt(
                url="https://www.wildberries.ru/catalog/311895731/detail.aspx",
                source="api",
                status="blocked",
                http_status=403,
                latency_ms=42,
            )
        )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["marketplace"], "wildberries")
        self.assertEqual(attempts[0]["source"], "api")
        self.assertEqual(attempts[0]["status"], "blocked")
        self.assertEqual(attempts[0]["http_status"], 403)
        self.assertEqual(attempts[0]["latency_ms"], 42)

    def test_wbbasket_candidates_prioritize_expected_host(self):
        self.assertEqual(_get_basket_host(311895731), "https://basket-19.wb.ru")
        candidates = _wbbasket_candidates(311895731)
        self.assertEqual(candidates[0], "19")
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertIn("37", _wbbasket_candidates(757984979))

    def test_wb_basket_host_boundaries(self):
        cases = [
            (14300000, "https://basket-01.wb.ru"),
            (14400000, "https://basket-02.wb.ru"),
            (240500000, "https://basket-15.wb.ru"),
            (240600000, "https://basket-16.wb.ru"),
            (262100000, "https://basket-16.wb.ru"),
            (262200000, "https://basket-17.wb.ru"),
            (283700000, "https://basket-17.wb.ru"),
            (283800000, "https://basket-18.wb.ru"),
            (305900000, "https://basket-18.wb.ru"),
            (306000000, "https://basket-19.wb.ru"),
            (348700000, "https://basket-20.wb.ru"),
            (348800000, "https://basket-21.wb.ru"),
            (373200000, "https://basket-22.wb.ru"),
            (757984979, "https://basket-37.wb.ru"),
        ]
        for nm_id, expected_host in cases:
            with self.subTest(nm_id=nm_id):
                self.assertEqual(_get_basket_host(nm_id), expected_host)

    def test_wb_image_url_for_high_article_uses_new_basket_range(self):
        self.assertEqual(
            _build_wb_image_url(757984979),
            "https://basket-37.wb.ru/vol7579/part757984/757984979/images/big/1.webp",
        )
        self.assertEqual(
            _build_wb_image_url(757984979, basket="38"),
            "https://basket-38.wb.ru/vol7579/part757984/757984979/images/big/1.webp",
        )

    def test_ozon_html_parser(self):
        html = """
        <html>
          <head><title>Fallback title</title></head>
          <body>
            <h1>Car Phone Holder</h1>
            <div data-widget="webPrice"><span>1 299 ₽</span></div>
            <div data-widget="webAddToCart"><button>Cart</button></div>
            <div data-widget="webGallery"><img src="https://cdn.example/img.webp"></div>
          </body>
        </html>
        """
        data = parse_ozon_html(html, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Car Phone Holder")
        self.assertEqual(data["price"], 1299)
        self.assertEqual(data["availability"], "in_stock")
        self.assertEqual(data["image_url"], "https://cdn.example/img.webp")

    def test_ozon_html_parser_accepts_lazy_and_protocol_relative_images(self):
        html = """
        <html>
          <head><title>Fallback title</title></head>
          <body>
            <h1>Car Phone Holder</h1>
            <div data-widget="webPrice"><span>1 299 руб</span></div>
            <div data-widget="webGallery">
              <img data-srcset="//cdn.example/small.webp 1x, //cdn.example/big.webp 2x">
            </div>
          </body>
        </html>
        """
        data = parse_ozon_html(html, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["image_url"], "https://cdn.example/small.webp")

    def test_ozon_html_ignores_unrelated_out_of_stock_text(self):
        html = """
        <html>
          <body>
            <h1>Car Phone Holder</h1>
            <div data-widget="webPrice"><span>248 ₽</span></div>
            <div data-widget="webAddToCart"><button>В корзину</button></div>
            <section data-widget="recommendations">Нет в наличии у другого товара</section>
          </body>
        </html>
        """
        data = parse_ozon_html(html, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["price"], 248)
        self.assertEqual(data["availability"], "in_stock")

    def test_ozon_html_detects_product_out_of_stock_widget(self):
        html = """
        <html>
          <body>
            <h1>Car Phone Holder</h1>
            <div data-widget="webPrice"><span>248 ₽</span></div>
            <div data-widget="webOutOfStock">Сообщить о поступлении</div>
          </body>
        </html>
        """
        data = parse_ozon_html(html, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["availability"], "out_of_stock")

    def test_ozon_api_json_parser(self):
        payload = {
            "seo": {"title": "Fallback name | Ozon"},
            "widgetStates": {
                "webProductHeading": '{"title": "Car Phone Holder"}',
                "webPrice": '{"price": "1 299 ₽"}',
                "webGallery": '{"imageUrl": "https://cdn.example/img.webp"}',
            },
        }
        data = parse_ozon_api_json(payload, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Car Phone Holder")
        self.assertEqual(data["price"], 1299)
        self.assertEqual(data["availability"], "in_stock")
        self.assertEqual(data["image_url"], "https://cdn.example/img.webp")

    def test_extract_ozon_incident_id(self):
        html = """
        <div>Инцидент: fab_20260513135442_01KRGSWJD6CKQGNWZE2724K1E7</div>
        <a href="/support/?incident_id=fab_query_123&token=abc">Support</a>
        """
        self.assertEqual(
            _extract_ozon_incident_id(html),
            "fab_20260513135442_01KRGSWJD6CKQGNWZE2724K1E7",
        )

    def test_parse_ozon_search_results(self):
        html = """
        <div data-widget="searchResultsV2">
          <div>
            <div>
              <a href="/product/phone-holder-123"><span class="tile-hover-target">Phone Holder</span></a>
              <span class="price">599 ₽</span>
              <img src="https://cdn.example/holder.webp">
            </div>
          </div>
        </div>
        """
        results = _parse_search_results(html, 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Phone Holder")
        self.assertEqual(results[0]["price"], 599)
        self.assertEqual(results[0]["url"], "https://www.ozon.ru/product/phone-holder-123")


class OzonUpdaterTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_url_tries_browser_after_api_block_by_default(self):
        class FakeUpdater(OzonUpdater):
            def __init__(self):
                super().__init__(db=None)
                self.browser_called = False

            async def _fetch_via_api(self, url):
                self._last_ozon_api_blocked = True
                return None

            async def _fetch(self, url):
                self.browser_called = True
                return """
                <html>
                  <body>
                    <h1>Car Phone Holder</h1>
                    <div data-widget="webPrice"><span>1 299 RUB</span></div>
                    <div data-widget="webAddToCart"><button>Cart</button></div>
                  </body>
                </html>
                """

        updater = FakeUpdater()
        with patch.dict("os.environ", {}, clear=True):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertTrue(updater.browser_called)
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Car Phone Holder")

    async def test_process_url_can_skip_browser_after_api_block(self):
        class FakeUpdater(OzonUpdater):
            def __init__(self):
                super().__init__(db=None)
                self.browser_called = False

            async def _fetch_via_api(self, url):
                self._last_ozon_api_blocked = True
                return None

            async def _fetch(self, url):
                self.browser_called = True
                return "<html><body><h1>Should not load</h1></body></html>"

        updater = FakeUpdater()
        with patch.dict("os.environ", {"OZON_SKIP_BROWSER_AFTER_API_BLOCK": "1"}, clear=True):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertFalse(updater.browser_called)
        self.assertIsNone(data)

    async def test_process_url_records_parse_error_and_clears_product_context(self):
        attempts = []

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {"strategy": "normal", "skip": False, "skip_browser": False}

            async def record_scrape_attempt(self, **kwargs):
                attempts.append(kwargs)

        class FakeUpdater(OzonUpdater):
            def __init__(self):
                super().__init__(db=FakeDB())

            async def _fetch_via_api(self, url):
                return None

            async def _fetch(self, url):
                return "<html><body></body></html>"

        updater = FakeUpdater()
        data = await updater.process_url("https://www.ozon.ru/product/test", product_id=42)

        self.assertIsNone(data)
        self.assertIsNone(updater._current_product_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["product_id"], 42)
        self.assertEqual(attempts[0]["source"], "parse")
        self.assertEqual(attempts[0]["status"], "parse_error")

    async def test_process_url_adaptive_strategy_skips_recent_blocked_url(self):
        attempts = []

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "defer_same_url",
                    "skip": True,
                    "skip_browser": True,
                    "reason": "same URL recently blocked by browser",
                    "cooldown_sec": 600,
                }

            async def record_scrape_attempt(self, **kwargs):
                attempts.append(kwargs)

        class FakeUpdater(OzonUpdater):
            def __init__(self):
                super().__init__(db=FakeDB())
                self.api_called = False
                self.browser_called = False

            async def _fetch_via_api(self, url):
                self.api_called = True
                return None

            async def _fetch(self, url):
                self.browser_called = True
                return "<html><body><h1>Should not load</h1></body></html>"

        updater = FakeUpdater()
        data = await updater.process_url("https://www.ozon.ru/product/test", product_id=42)

        self.assertIsNone(data)
        self.assertFalse(updater.api_called)
        self.assertFalse(updater.browser_called)
        self.assertEqual(attempts[0]["source"], "strategy")
        self.assertEqual(attempts[0]["status"], "skipped")
        self.assertEqual(attempts[0]["strategy"], "defer_same_url")

    async def test_update_all_does_not_duplicate_blocked_history(self):
        callbacks = []
        added_history = []
        product = SimpleNamespace(
            id=7,
            name="Ozon blocked item",
            url="https://www.ozon.ru/product/test",
        )

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def add(self, row):
                added_history.append(row)

            async def commit(self):
                return None

        class FakeDB:
            async def get_all_products(self):
                return [product]

            async def get_last_price(self, product_id):
                return SimpleNamespace(availability_status="blocked")

            def session(self):
                return FakeSession()

        class FakeUpdater(OzonUpdater):
            async def process_url(self, url, product_id=None):
                self.seen_product_id = product_id
                return None

            async def _human_delay(self, *args, **kwargs):
                return None

        updater = FakeUpdater(db=FakeDB())

        async def callback(text):
            callbacks.append(text)

        updated, changes = await updater.update_all(callback=callback)

        self.assertEqual(updated, 0)
        self.assertEqual(changes, [])
        self.assertEqual(added_history, [])
        self.assertEqual(updater.seen_product_id, 7)
        self.assertEqual(callbacks, ["⚠️ Ozon временно заблокировал: Ozon blocked item"])
