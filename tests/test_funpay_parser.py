import unittest

from app.parsers.funpay import (
    build_funpay_search_query,
    is_funpay_offer_url,
    parse_funpay_offer_html,
)


FUNPAY_OFFER_HTML = """
<html>
  <body>
    <div class="back-link"><a><span class="inside">Подписка ChatGPT</span></a></div>
    <div class="param-list">
      <div class="param-item"><h5>Тип подписки</h5><div class="text-bold">Plus</div></div>
      <div class="param-item"><h5>Способ получения</h5><div class="text-bold">С заходом на аккаунт</div></div>
      <div class="param-item"><h5>Была подписка</h5><div class="text-bold">Да</div></div>
      <div class="param-item"><h5>Краткое описание</h5><div>🍈 Chat GPT 5🌟 PLUS Подписка 🌟1 МЕСЯЦ 🔋 НА ВАШ АККАУНТ 🔋 30 ДНЕЙ 🌍 ЛЮБОЙ АКК 🌍 Гарантии 🍈</div></div>
      <div class="param-item"><h5>Подробное описание</h5><div>Регион ГЛОБАЛЬНЫЙ, включая Россию и РБ!</div></div>
    </div>
    <div class="media-user-name"><a href="/users/241092/">Fludy</a></div>
    <div class="seller-promo-desc"><a>99 786 отзывов за 9 лет</a></div>
    <select>
      <option data-cy="rub" data-factors="1602.44,1.0183299389002,1">СБП</option>
      <option data-cy="rub" data-factors="1704.73,1.063829787234,1">Банковская карта RU</option>
    </select>
  </body>
</html>
"""


class FunPayParserTests(unittest.TestCase):
    def test_detects_funpay_offer_url(self):
        self.assertTrue(is_funpay_offer_url("https://funpay.com/lots/offer?id=68683803"))
        self.assertTrue(is_funpay_offer_url("https://www.funpay.com/lots/offer?id=68683803"))
        self.assertFalse(is_funpay_offer_url("https://funpay.com/lots/3559/"))

    def test_parse_funpay_offer_html(self):
        offer = parse_funpay_offer_html(
            FUNPAY_OFFER_HTML,
            "https://funpay.com/lots/offer?id=68683803",
        )

        self.assertEqual(offer.category, "Подписка ChatGPT")
        self.assertEqual(offer.params["Тип подписки"], "Plus")
        self.assertEqual(offer.seller, "Fludy")
        self.assertEqual(offer.seller_reviews, "99 786 отзывов за 9 лет")
        self.assertEqual(offer.price_rub, 1602.44)
        self.assertIn("Chat GPT 5", offer.short_description)

    def test_build_funpay_search_query_uses_product_words(self):
        offer = parse_funpay_offer_html(
            FUNPAY_OFFER_HTML,
            "https://funpay.com/lots/offer?id=68683803",
        )

        query = build_funpay_search_query(offer)

        self.assertEqual(query, "ChatGPT Plus подписка 1 месяц")
        self.assertLessEqual(len(query), 160)


if __name__ == "__main__":
    unittest.main()
