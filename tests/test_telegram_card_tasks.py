import unittest
from types import SimpleNamespace

from app.telegram_card_tasks import build_card_task_from_product, build_card_task_from_url


class TelegramCardTaskTests(unittest.TestCase):
    def test_build_card_task_from_ozon_url_uses_slug_as_title(self):
        task = build_card_task_from_url(
            "https://www.ozon.ru/product/avm-center-kabel-dlya-mobilnyh-ustroystv-usb-type-c-apple-lightning-micro-usb-2-0-type-b-1-m-siniy-904750846/"
        )

        self.assertIn("\u0442\u043e\u0432\u0430\u0440: Avm center kabel dlya mobilnyh ustroystv usb type c", task)
        self.assertIn("\u0414\u0430\u043d\u043d\u044b\u0435 \u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u044b \u0438\u0437 \u0441\u0441\u044b\u043b\u043a\u0438", task)

    def test_build_card_task_from_product_includes_price_image_and_source(self):
        product = SimpleNamespace(
            name="РљР°Р±РµР»СЊ USB-C",
            image_url="https://example.com/image.jpg",
            url="https://example.com/product",
        )

        task = build_card_task_from_product(product, 299)

        self.assertIn("РљР°Р±РµР»СЊ USB-C", task)
        self.assertIn("299", task)
        self.assertIn("https://example.com/image.jpg", task)
        self.assertIn("https://example.com/product", task)
