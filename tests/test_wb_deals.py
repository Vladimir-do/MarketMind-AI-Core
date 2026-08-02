import unittest

from app.parsers.base import ProductData
from app.wb_deals import find_wb_deals


class WBDealsTests(unittest.TestCase):
    def test_find_wb_deals_filters_by_discount(self):
        products = [
            ProductData(
                name="Кресло 1",
                price=7500,
                old_price=12000,
                discount_pct=38,
                availability="in_stock",
                url="https://www.wildberries.ru/catalog/1/detail.aspx",
                image_url=None,
                marketplace="wildberries",
            ),
            ProductData(
                name="Кресло 2",
                price=9000,
                old_price=10000,
                discount_pct=10,
                availability="in_stock",
                url="https://www.wildberries.ru/catalog/2/detail.aspx",
                image_url=None,
                marketplace="wildberries",
            ),
        ]

        deals = find_wb_deals(products, min_discount_pct=30, limit=10)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["name"], "Кресло 1")
        self.assertEqual(deals[0]["discount_pct"], 38)

    def test_find_wb_deals_calculates_discount_if_missing(self):
        products = [
            ProductData(
                name="Товар",
                price=700,
                old_price=1000,
                discount_pct=None,
                availability="in_stock",
                url="https://www.wildberries.ru/catalog/3/detail.aspx",
                image_url=None,
                marketplace="wildberries",
            ),
        ]
        deals = find_wb_deals(products, min_discount_pct=25, limit=10)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["discount_pct"], 30)


if __name__ == "__main__":
    unittest.main()
