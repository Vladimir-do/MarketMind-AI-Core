import json
import unittest

from app.parsers.yandex_market import parse_yandex_market_search_html, YandexMarketParser


class YandexMarketSearchTests(unittest.TestCase):
    def _html(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "item": {
                    "@type": "Product", "name": "Наушники Baseus One",
                    "url": "https://market.yandex.ru/card/baseus-one/111",
                    "image": "https://img.example/one.jpg",
                    "brand": {"@type": "Brand", "name": "Baseus"},
                    "offers": {"@type": "Offer", "price": 2100, "availability": "https://schema.org/InStock"},
                    "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.8, "reviewCount": 25},
                }},
                {"@type": "ListItem", "position": 2, "item": {
                    "@type": "Product", "name": "Наушники Baseus Two",
                    "url": "https://market.yandex.ru/card/baseus-two/222",
                    "image": "https://img.example/two.jpg",
                    "offers": {"@type": "Offer", "price": 3200},
                }},
            ],
        }
        # Search pages may repeat each Product node outside ItemList; duplicates must collapse.
        repeated = payload["itemListElement"][0]["item"]
        return '<html><script type="application/ld+json">' + json.dumps([payload, repeated]) + '</script></html>'

    def test_search_returns_real_individual_product_urls_and_prices(self):
        products = parse_yandex_market_search_html(self._html(), max_results=5)
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].url, "https://market.yandex.ru/card/baseus-one/111")
        self.assertEqual(products[0].price, 2100)
        self.assertEqual(products[0].rating, 4.8)
        self.assertEqual(products[0].reviews_count, 25)
        self.assertEqual(products[1].url, "https://market.yandex.ru/card/baseus-two/222")
        self.assertEqual(products[1].price, 3200)

    def test_search_respects_limit_and_rejects_search_page_urls(self):
        html = self._html().replace(
            'https://market.yandex.ru/card/baseus-two/222',
            'https://market.yandex.ru/search?text=wrong',
        )
        products = parse_yandex_market_search_html(html, max_results=1)
        self.assertEqual(len(products), 1)
        self.assertNotIn('/search', products[0].url)

    def test_parser_exposes_search(self):
        self.assertTrue(callable(YandexMarketParser().search))
