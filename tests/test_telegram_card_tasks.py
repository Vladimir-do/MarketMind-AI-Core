import unittest
from types import SimpleNamespace

from app.telegram_card_tasks import (
    build_card_task_from_product,
    build_card_task_from_url,
    extract_ozon_product_identity,
)


class TelegramCardTaskTests(unittest.TestCase):
    def test_build_card_task_from_ozon_url_uses_slug_as_title(self):
        task = build_card_task_from_url(
            "https://www.ozon.ru/product/avm-center-kabel-dlya-mobilnyh-ustroystv-usb-type-c-apple-lightning-micro-usb-2-0-type-b-1-m-siniy-904750846/"
        )

        self.assertIn("\u0442\u043e\u0432\u0430\u0440: Avm center kabel dlya mobilnyh ustroystv usb type c", task)
        self.assertIn(
            "\u0414\u0430\u043d\u043d\u044b\u0435 \u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u044b \u0438\u0437 \u0441\u0441\u044b\u043b\u043a\u0438",
            task,
        )

    def test_extract_ozon_identity_from_product_url(self):
        title, product_id = extract_ozon_product_identity(
            "https://www.ozon.ru/product/kompleks-vitaminov-gruppy-v-magniy-immunit-shipuchie-tabletki-20-sht-823223431/?at=abc"
        )
        self.assertEqual(title, "Kompleks vitaminov gruppy v magniy immunit shipuchie tabletki 20 sht")
        self.assertEqual(product_id, "823223431")

    def test_url_fallback_includes_ozon_article_id_and_unverified_warning(self):
        task = build_card_task_from_url(
            "https://www.ozon.ru/product/kompleks-vitaminov-gruppy-v-magniy-immunit-shipuchie-tabletki-20-sht-823223431/"
        )
        self.assertIn("артикул Ozon: 823223431", task)
        self.assertIn("Проверить вручную", task)

    def test_product_fallback_marks_slug_name_unverified_when_no_price_or_image(self):
        product = SimpleNamespace(
            name="Kompleks vitaminov gruppy v magniy immunit shipuchie tabletki 20 sht",
            image_url=None,
            url="https://www.ozon.ru/product/kompleks-vitaminov-gruppy-v-magniy-immunit-shipuchie-tabletki-20-sht-823223431/",
        )
        task = build_card_task_from_product(product, None)
        self.assertIn("823223431", task)
        self.assertIn("не подтверждено страницей товара", task)

    def test_build_card_task_from_product_includes_price_image_and_source(self):
        product = SimpleNamespace(
            name="Кабель USB-C",
            image_url="https://example.com/image.jpg",
            url="https://example.com/product",
        )

        task = build_card_task_from_product(product, 299)

        self.assertIn("Кабель USB-C", task)
        self.assertIn("299", task)
        self.assertIn("https://example.com/image.jpg", task)
        self.assertIn("https://example.com/product", task)
