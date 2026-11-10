import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.parsers.alt_sources import extract_product_from_cache_html, fetch_from_alt_sources
from app.parsers.base import ProductData
from app.parsers.mcp_sources import normalize_mcp_product_payload
from app.parsers.ozon import OzonParser
from app.parsers.router import detect_marketplace
from app.parsers.wildberries import (
    WildberriesParser,
    _build_wb_image_url,
    _extract_wb_id,
    _extract_wb_products,
    _extract_wbbasket_prices,
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

    def test_yandex_market_extracts_explicit_reviews_and_seller(self):
        html = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Кофемолка",
          "review": [
            {"@type": "Review", "reviewBody": "Мелет быстро и равномерно."},
            {"@type": "Review", "reviewBody": "   Мелет быстро и равномерно.  "},
            {"@type": "Review", "reviewBody": "Шумновата ночью."},
            {"@type": "Review", "reviewBody": ""}
          ],
          "offers": {
            "@type": "Offer",
            "price": "2500",
            "seller": {"@type": "Organization", "name": "Магазин Пример"}
          }
        }
        </script>
        """
        data = parse_yandex_market_html(html, "https://market.yandex.ru/product--coffee/123")
        self.assertIsNotNone(data)
        self.assertEqual(data.seller_name, "Магазин Пример")
        self.assertEqual(data.reviews, ["Мелет быстро и равномерно.", "Шумновата ночью."])
        self.assertEqual(data.availability, "unknown")

    def test_yandex_market_does_not_invent_stock_or_accept_invalid_rating(self):
        html = """
        <script type="application/ld+json">
        {"@type":"Product", "name":"Товар", "aggregateRating":{"ratingValue":"8.9"}}
        </script>
        """
        data = parse_yandex_market_html(html, "https://market.yandex.ru/product--item/123")
        self.assertIsNotNone(data)
        self.assertIsNone(data.rating)
        self.assertEqual(data.availability, "unknown")

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

    def test_yandex_market_retries_transient_5xx_then_succeeds(self):
        html = "<html><body><h1>Тестовый товар</h1></body></html>"
        statuses = [503, 200]
        session_count = 0

        class FakeResponse:
            def __init__(self, status):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def text(self, errors="strict"):
                return html

        class FakeSession:
            def __init__(self, **kwargs):
                nonlocal session_count
                session_count += 1

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def get(self, url, timeout=None):
                return FakeResponse(statuses.pop(0))

        parser = YandexMarketParser()
        with (
            patch("app.parsers.yandex_market.aiohttp.ClientSession", side_effect=FakeSession),
            patch("app.parsers.yandex_market.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            data = asyncio.run(parser.fetch_product("https://market.yandex.ru/product--test/1"))

        self.assertIsNotNone(data)
        self.assertEqual(data.name, "Тестовый товар")
        self.assertEqual(session_count, 2)
        sleep.assert_awaited_once_with(1.0)

    def test_yandex_market_does_not_retry_rate_limit(self):
        session_count = 0

        class FakeResponse:
            status = 429

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def text(self, errors="strict"):
                return "rate limited"

        class FakeSession:
            def __init__(self, **kwargs):
                nonlocal session_count
                session_count += 1

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def get(self, url, timeout=None):
                return FakeResponse()

        attempts = []

        async def recorder(**kwargs):
            attempts.append(kwargs)

        parser = YandexMarketParser(attempt_recorder=recorder)
        with (
            patch("app.parsers.yandex_market.aiohttp.ClientSession", side_effect=FakeSession),
            patch("app.parsers.yandex_market.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            data = asyncio.run(parser.fetch_product("https://market.yandex.ru/product--test/1"))

        self.assertIsNone(data)
        self.assertEqual(session_count, 1)
        sleep.assert_not_awaited()
        self.assertEqual(attempts[0]["status"], "blocked")
        self.assertEqual(attempts[0]["http_status"], 429)

    def test_cache_html_service_title_is_ignored(self):
        html = "<html><head><title>Google Search</title></head><body></body></html>"

        self.assertIsNone(extract_product_from_cache_html(html, "https://www.ozon.ru/product/test"))

    def test_cache_html_extraction_includes_availability(self):
        html = """
        <html>
          <head>
            <title>Cached Product — Ozon</title>
            <meta property="og:image" content="https://cdn.example/product.webp">
          </head>
          <body>{"price": "1299"}</body>
        </html>
        """

        data = extract_product_from_cache_html(html, "https://www.ozon.ru/product/test")

        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Cached Product")
        self.assertEqual(data["price"], 1299)
        self.assertEqual(data["availability"], "unknown")

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

    def test_wildberries_can_handle_only_product_urls(self):
        self.assertTrue(WildberriesParser.can_handle("https://www.wildberries.ru/catalog/311895731/detail.aspx"))
        self.assertTrue(WildberriesParser.can_handle("https://www.wb.ru/catalog/311895731?targetUrl=XS"))
        self.assertFalse(WildberriesParser.can_handle("https://www.wildberries.ru/"))
        self.assertFalse(WildberriesParser.can_handle("https://www.wildberries.ru/catalog/"))

    def test_wb_v4_products_top_level_response(self):
        products = [{"id": 311895731, "name": "Headphones"}]
        self.assertEqual(_extract_wb_products({"products": products}), products)

    def test_wb_legacy_nested_products_response_remains_supported(self):
        products = [{"id": 311895731, "name": "Headphones"}]
        self.assertEqual(_extract_wb_products({"data": {"products": products}}), products)

    def test_wb_products_rejects_malformed_payload(self):
        self.assertEqual(_extract_wb_products(None), [])
        self.assertEqual(_extract_wb_products({"products": "not-a-list"}), [])

    def test_wbbasket_price_skips_sizes_without_price(self):
        price, old_price = _extract_wbbasket_prices(
            [
                {"name": "size without price"},
                {"price": None},
                {"price": {"total": 0, "basic": 10000}},
                {"price": {"total": 129900, "basic": 199900}},
            ]
        )

        self.assertEqual(price, 1299)
        self.assertEqual(old_price, 1999)

    def test_wbbasket_price_handles_malformed_sizes_and_equal_old_price(self):
        self.assertEqual(
            _extract_wbbasket_prices([None, "invalid", {"price": []}]),
            (None, None),
        )
        self.assertEqual(
            _extract_wbbasket_prices([{"price": {"total": 129900, "basic": 129900}}]),
            (1299, None),
        )

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

    def test_wildberries_product_without_stock_rows_is_unknown_not_out_of_stock(self):
        data = WildberriesParser()._parse_product(
            {
                "name": "Органайзер",
                "brand": "Brand",
                "sizes": [{"price": {"product": 50000}}],
            },
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            311895731,
            session=None,
        )

        self.assertEqual(data.availability, "unknown")
        self.assertEqual(data.brand, "Brand")

    def test_wildberries_product_with_explicit_zero_stock_is_out_of_stock(self):
        data = WildberriesParser()._parse_product(
            {
                "name": "Органайзер",
                "sizes": [{"stocks": [{"qty": 0}]}],
            },
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            311895731,
            session=None,
        )

        self.assertEqual(data.availability, "out_of_stock")

    def test_wildberries_brand_is_not_misreported_as_seller(self):
        data = WildberriesParser()._parse_product(
            {
                "name": "Наушники",
                "brand": "Acme",
                "supplier": "ООО Продавец",
                "supplierRating": 4.9,
                "sizes": [{"stocks": [{"qty": 1}]}],
            },
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            311895731,
            session=None,
        )

        self.assertEqual(data.brand, "Acme")
        self.assertEqual(data.seller_name, "ООО Продавец")
        self.assertEqual(data.seller_rating, 4.9)

    def test_wildberries_cloud_payload_missing_availability_is_unknown(self):
        data = WildberriesParser()._parse_cloud_payload(
            {"name": "Товар", "price": 100, "brand": "Acme"},
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            311895731,
        )

        self.assertIsNotNone(data)
        self.assertEqual(data.availability, "unknown")

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

    def test_wb_search_query_variants_for_magnesium_vitamins(self):
        variants = WildberriesParser._search_query_variants("витамины с магнием")

        self.assertIn("витамины с магнием", variants)
        self.assertIn("магнием", variants)
        self.assertIn("витамины магнием", variants)
        self.assertIn("магний цитрат", variants)

    def test_wb_search_without_stock_rows_returns_unknown_availability(self):
        parser = WildberriesParser()

        class FakeResp:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def text(self):
                import json

                return json.dumps(
                    {
                        "data": {
                            "products": [
                                {
                                    "id": 123456789,
                                    "name": "Органайзер для проводов",
                                    "sizes": [{"price": {"product": 50000}}],
                                }
                            ]
                        }
                    }
                )

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
            results = asyncio.run(parser.search("органайзер для проводов", max_results=5))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].availability, "unknown")

    def test_wb_search_extracts_top_level_products(self):
        data = {
            "metadata": {"name": "магний"},
            "products": [{"id": 822673620, "name": "Магнерот"}],
        }

        self.assertEqual(WildberriesParser._extract_search_products(data), data["products"])

    def test_wb_search_extracts_nested_products(self):
        data = {
            "data": {
                "products": [{"id": 757984979, "name": "Магний цитрат"}],
            }
        }

        self.assertEqual(WildberriesParser._extract_search_products(data), data["data"]["products"])

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
        self.assertEqual(data["availability"], "unknown")
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

    def test_ozon_html_without_stock_evidence_returns_unknown(self):
        html = """
        <html><body>
          <h1>Car Phone Holder</h1>
          <div data-widget="webPrice"><span>248 ₽</span></div>
        </body></html>
        """
        data = parse_ozon_html(html, "https://www.ozon.ru/product/test")
        self.assertIsNotNone(data)
        self.assertEqual(data["availability"], "unknown")

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
        self.assertEqual(data["availability"], "unknown")
        self.assertEqual(data["image_url"], "https://cdn.example/img.webp")

    def test_ozon_api_json_parser_extracts_explicit_review_signals(self):
        payload = {
            "widgetStates": {
                "webProductHeading": '{"title": "Car Phone Holder"}',
                "webPrice": '{"price": "1 299 ₽"}',
                "webReviewSummary": '{"aggregateRating": {"ratingValue": "4.8", "reviewCount": "153"}, "reviews": [{"text": "Крепкий держатель"}, {"text": "Удобно пользоваться"}]}',
            },
        }
        data = parse_ozon_api_json(payload, "https://www.ozon.ru/product/test")
        self.assertEqual(data["rating"], 4.8)
        self.assertEqual(data["reviews_count"], 153)
        self.assertEqual(data["reviews"], ["Крепкий держатель", "Удобно пользоваться"])

    def test_ozon_api_json_parser_does_not_invent_missing_review_signals(self):
        data = parse_ozon_api_json(
            {"widgetStates": {"webProductHeading": '{"title": "Car Phone Holder"}'}},
            "https://www.ozon.ru/product/test",
        )
        self.assertIsNone(data["rating"])
        self.assertIsNone(data["reviews_count"])
        self.assertEqual(data["reviews"], [])

    def test_mcp_product_payload_normalizer(self):
        data = normalize_mcp_product_payload(
            {
                "title": "MCP Product",
                "price": "1 299 ₽",
                "availability": "in_stock",
                "imageUrl": "https://cdn.example/image.webp",
                "brand": "MCPBrand",
            },
            "https://www.ozon.ru/product/test",
        )

        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "MCP Product")
        self.assertEqual(data["price"], 1299)
        self.assertEqual(data["availability"], "in_stock")
        self.assertEqual(data["source"], "mcp")

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
    async def test_dump_debug_rotates_to_50_and_keeps_latest_incident(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_dir = Path(temp_dir)
            for index in range(51):
                stem = f"20200101_000000_incident_{index:02}"
                (debug_dir / f"{stem}.png").write_bytes(b"old png")
                (debug_dir / f"{stem}.html").write_text("old html", encoding="utf-8")
            research_dump = debug_dir / "20200101_000000_research.md"
            research_dump.write_text("keep", encoding="utf-8")

            async def write_screenshot(*, path, full_page):
                Path(path).write_bytes(b"latest png")

            page = SimpleNamespace(
                screenshot=AsyncMock(side_effect=write_screenshot),
                content=AsyncMock(return_value="latest html"),
            )
            updater = OzonUpdater.__new__(OzonUpdater)
            with patch.object(updater, "_debug_dir", return_value=debug_dir):
                await updater._dump_debug(page, "incident")

            timestamped = {
                path.stem
                for path in debug_dir.iterdir()
                if path.suffix in {".png", ".html"}
                and path.name != "last_incident.png"
                and path.name != "last_incident.html"
            }
            self.assertEqual(len(timestamped), 50)
            self.assertEqual((debug_dir / "last_incident.png").read_bytes(), b"latest png")
            self.assertEqual((debug_dir / "last_incident.html").read_text(encoding="utf-8"), "latest html")
            self.assertTrue(research_dump.exists())

    async def test_alt_sources_uses_mcp_before_cache(self):
        expected = {
            "url": "https://www.ozon.ru/product/test",
            "name": "MCP Product",
            "price": 1299,
            "availability": "in_stock",
            "image_url": "https://cdn.example/image.webp",
            "source": "mcp",
        }

        with (
            patch("app.parsers.alt_sources.fetch_product_via_mcp", AsyncMock(return_value=expected)) as mcp,
            patch("app.parsers.alt_sources.fetch_via_google_cache", AsyncMock()) as google_cache,
            patch("app.parsers.alt_sources.fetch_via_yandex_cache", AsyncMock()) as yandex_cache,
        ):
            data = await fetch_from_alt_sources("https://www.ozon.ru/product/test")

        self.assertEqual(data, expected)
        mcp.assert_awaited_once()
        google_cache.assert_not_awaited()
        yandex_cache.assert_not_awaited()

    async def test_ozon_parser_can_skip_browser_after_api_block(self):
        class FakeOzonParser(OzonParser):
            def __init__(self):
                super().__init__()
                self.html_called = False

            async def _fetch_api_data(self, url):
                self._last_api_blocked = True
                return None

            async def _fetch_html(self, url):
                self.html_called = True
                return "<html><body><h1>Should not load</h1></body></html>"

        parser = FakeOzonParser()
        with (
            patch.dict("os.environ", {"OZON_SKIP_BROWSER_AFTER_API_BLOCK": "1"}, clear=True),
            patch("app.parsers.ozon.fetch_from_alt_sources", AsyncMock(return_value=None)),
        ):
            data = await parser.fetch_product("https://www.ozon.ru/product/test")

        self.assertIsNone(data)
        self.assertFalse(parser.html_called)

    async def test_ozon_parser_uses_alt_source_after_api_block(self):
        class FakeOzonParser(OzonParser):
            async def _fetch_api_data(self, url):
                self._last_api_blocked = True
                return None

            async def _fetch_html(self, url):
                raise AssertionError("browser fallback should not run")

        parser = FakeOzonParser()
        with (
            patch.dict("os.environ", {"OZON_SKIP_BROWSER_AFTER_API_BLOCK": "1"}, clear=True),
            patch(
                "app.parsers.ozon.fetch_from_alt_sources",
                AsyncMock(
                    return_value={
                        "name": "MCP Product",
                        "price": 1299,
                        "availability": "in_stock",
                        "image_url": "https://cdn.example/image.webp",
                        "brand": "MCPBrand",
                    }
                ),
            ),
        ):
            data = await parser.fetch_product("https://www.ozon.ru/product/test")

        self.assertIsNotNone(data)
        self.assertEqual(data.name, "MCP Product")
        self.assertEqual(data.price, 1299)
        self.assertEqual(data.brand, "MCPBrand")

    async def test_ozon_parser_stops_browser_when_started_by_fetch_product(self):
        class FakeOzonParser(OzonParser):
            def __init__(self):
                super().__init__()
                self.stop_called = False

            async def _fetch_api_data(self, url):
                return None

            async def _fetch_html(self, url):
                self._browser = object()
                return """
                <html>
                  <body>
                    <h1>Car Phone Holder</h1>
                    <div data-widget="webPrice"><span>1 299 RUB</span></div>
                    <div data-widget="webAddToCart"><button>Cart</button></div>
                  </body>
                </html>
                """

            async def stop(self):
                self.stop_called = True
                self._browser = None

        parser = FakeOzonParser()
        data = await parser.fetch_product("https://www.ozon.ru/product/test")

        self.assertIsNotNone(data)
        self.assertEqual(data.name, "Car Phone Holder")
        self.assertTrue(parser.stop_called)
        self.assertIsNone(parser._browser)

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
        with (
            patch.dict("os.environ", {"OZON_SKIP_BROWSER_AFTER_API_BLOCK": "1"}, clear=True),
            patch("app.updater.fetch_from_alt_sources", AsyncMock(return_value=None)),
        ):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertFalse(updater.browser_called)
        self.assertIsNone(data)

    async def test_process_url_uses_alt_source_when_api_blocked_and_browser_skipped(self):
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
        with (
            patch.dict("os.environ", {"OZON_SKIP_BROWSER_AFTER_API_BLOCK": "1"}, clear=True),
            patch(
                "app.updater.fetch_from_alt_sources",
                AsyncMock(
                    return_value={
                        "name": "MCP Product",
                        "price": 1299,
                        "availability": "in_stock",
                        "image_url": "https://cdn.example/image.webp",
                    }
                ),
            ),
        ):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertFalse(updater.browser_called)
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "MCP Product")

    async def test_process_url_uses_alt_source_after_adaptive_api_skip(self):
        attempts = []

        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "self_heal_disable_api",
                    "skip": False,
                    "skip_api": True,
                    "skip_browser": False,
                    "reason": "recent API blocks",
                    "cooldown_sec": 7200,
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
        with patch(
            "app.updater.fetch_from_alt_sources",
            AsyncMock(
                return_value={
                    "name": "MCP Product",
                    "price": 1299,
                    "availability": "in_stock",
                    "image_url": "https://cdn.example/image.webp",
                }
            ),
        ):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertFalse(updater.api_called)
        self.assertFalse(updater.browser_called)
        self.assertEqual(data["name"], "MCP Product")
        self.assertEqual(attempts[0]["source"], "api")
        self.assertEqual(attempts[0]["status"], "skipped")

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
        with patch("app.updater.fetch_from_alt_sources", AsyncMock(return_value=None)):
            data = await updater.process_url("https://www.ozon.ru/product/test", product_id=42)

        self.assertIsNone(data)
        self.assertFalse(updater.api_called)
        self.assertFalse(updater.browser_called)
        self.assertEqual(attempts[0]["source"], "strategy")
        self.assertEqual(attempts[0]["status"], "skipped")
        self.assertEqual(attempts[0]["strategy"], "defer_same_url")

    async def test_process_url_uses_alt_source_after_adaptive_full_skip(self):
        class FakeDB:
            async def recommend_scrape_strategy(self, marketplace, *, url=None):
                return {
                    "strategy": "defer_same_url",
                    "skip": True,
                    "skip_browser": True,
                    "reason": "same URL recently blocked by browser",
                    "cooldown_sec": 600,
                }

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
        with patch(
            "app.updater.fetch_from_alt_sources",
            AsyncMock(
                return_value={
                    "name": "MCP Product",
                    "price": 1299,
                    "availability": "in_stock",
                    "image_url": "https://cdn.example/image.webp",
                }
            ),
        ):
            data = await updater.process_url("https://www.ozon.ru/product/test")

        self.assertFalse(updater.api_called)
        self.assertFalse(updater.browser_called)
        self.assertEqual(data["name"], "MCP Product")

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

    async def test_update_all_continues_batch_after_one_product_raises(self):
        """Regression for OZON-BATCH: a single product's process_url()
        raising (e.g. Playwright/browser failure) must not abort the rest
        of the batch -- update_all() must still process and report the
        remaining products instead of letting the whole run silently drop
        to 0 updated."""
        callbacks = []
        added_history = []
        product_failing = SimpleNamespace(
            id=1,
            name="Crashes during fetch",
            url="https://www.ozon.ru/product/fail",
        )
        product_ok = SimpleNamespace(
            id=2,
            name="Works fine",
            url="https://www.ozon.ru/product/ok",
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
                return [product_failing, product_ok]

            async def get_last_price(self, product_id):
                return None

            def session(self):
                return FakeSession()

            async def save_product(self, url, data):
                return None, True

        class FakeUpdater(OzonUpdater):
            async def process_url(self, url, product_id=None):
                if product_id == 1:
                    raise RuntimeError("Playwright browser crashed (test)")
                return {"name": "Works fine", "price": 100, "availability": "in_stock"}

            async def _wait_for_network(self, *args, **kwargs):
                return None

        updater = FakeUpdater(db=FakeDB())

        async def callback(text):
            callbacks.append(text)

        updated, changes = await updater.update_all(callback=callback)

        # The failing product must not have been counted as updated, but
        # the second product must still have been reached and processed.
        self.assertEqual(updated, 1)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["name"], "Works fine")
        self.assertTrue(any("Works fine" in text for text in callbacks))
        self.assertEqual(added_history, [])
        self.assertTrue(any("Ошибка при обновлении" in text for text in callbacks))
        self.assertFalse(any("Ozon временно заблокировал" in text for text in callbacks))
