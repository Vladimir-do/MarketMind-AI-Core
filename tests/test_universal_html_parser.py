import csv
import io
import unittest

from app.universal_parsing_core import Router, UniversalHtmlParser
from app.universal_parsing_core.algorithms.confidence import calculate_confidence
from app.universal_parsing_core.algorithms.page_structure_detector import detect_page_structure
from app.universal_parsing_core.exporters import export_csv, export_json
from app.universal_parsing_core.schemas.normalized_entity import NormalizedEntity
from app.universal_parsing_core.schemas.page_structure import PageStructure
from app.universal_parsing_core.schemas.parse_context import ParseContext
from app.universal_parsing_core.schemas.task_type import TaskType


class UniversalHtmlParserTests(unittest.TestCase):
    def test_extracts_price_entity_from_inline_html(self):
        html = """
        <html>
          <body>
            <h1>Меню</h1>
            <div>Шашлык из свинины 350 ₽</div>
          </body>
        </html>
        """

        result = UniversalHtmlParser().parse("https://example.com/menu", html=html)

        self.assertTrue(result.success)
        self.assertEqual(result.parser_used, "universal_html")
        self.assertEqual(result.page_structure, PageStructure.SINGLE)
        self.assertEqual(result.entities[0].title, "Шашлык из свинины")
        self.assertEqual(result.entities[0].price, 350)
        self.assertEqual(result.entities[0].entity_type, "dish")
        self.assertEqual(result.confidence, 0.75)
        self.assertGreaterEqual(result.execution_time_ms, 0)

    def test_price_without_title_has_low_confidence(self):
        result = UniversalHtmlParser().parse(
            "https://example.com/menu",
            html="<html><body><div>350 в‚Ѕ</div></body></html>",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.entities[0].price, 350)
        self.assertEqual(result.confidence, 0.30)
        self.assertIn("Low confidence: price found without a reliable title", result.warnings)

    def test_title_price_and_detail_link_have_high_confidence(self):
        confidence = calculate_confidence(
            [
                NormalizedEntity(
                    entity_type="dish",
                    title="РЁР°С€Р»С‹Рє",
                    price=350,
                    url="https://example.com/menu/shashlyk",
                    attributes={"url_source": "detail_link"},
                )
            ],
            page_structure=PageStructure.CATALOG,
            has_title=True,
        )

        self.assertGreaterEqual(confidence, 0.85)

    def test_ai_source_adds_warning(self):
        context = ParseContext(
            url="https://example.com/menu",
            html="<html><body><div>РЁР°С€Р»С‹Рє 350 в‚Ѕ</div></body></html>",
            parser_chain=["ai_enricher", "universal_html"],
        )

        result = UniversalHtmlParser().parse(context)

        self.assertIn("Data was extracted or enriched by AI; verify before using", result.warnings)

    def test_empty_html_returns_empty_structure(self):
        result = UniversalHtmlParser().parse(
            "https://example.com/empty",
            html="<html><body><h1>Only text</h1></body></html>",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.page_structure, PageStructure.EMPTY)
        self.assertEqual(result.entities, [])
        self.assertIn("no entities found", result.warnings)

    def test_loading_html_recovers_with_browser_next_strategy(self):
        result = UniversalHtmlParser().parse(
            "https://example.com/loading",
            html="""
            <html>
            <body>
            <div>Загрузка...</div>
            </body>
            </html>
            """,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.page_structure, PageStructure.EMPTY)
        self.assertEqual(result.entities, [])
        self.assertEqual(result.warnings, ["no entities found"])
        self.assertEqual(result.next_strategy, "browser")

    def test_detects_catalog_without_requiring_prices(self):
        html = """
        <html><body>
          <article class="product_pod"><h3><a href="item-one_1/index.html">One</a></h3></article>
          <article class="product_pod"><h3><a href="item-two_2/index.html">Two</a></h3></article>
          <article class="product_pod"><h3><a href="item-three_3/index.html">Three</a></h3></article>
          <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
        </body></html>
        """

        result = UniversalHtmlParser().parse("https://example.com/catalog", html=html)

        self.assertTrue(result.success)
        self.assertEqual(detect_page_structure(html), PageStructure.CATALOG)
        self.assertEqual(result.task_type, TaskType.UNIVERSAL_CATALOG)
        self.assertEqual(result.page_structure, PageStructure.CATALOG)
        self.assertEqual(result.entities, [])
        self.assertGreaterEqual(result.confidence, 0.85)

    def test_useful_unstructured_html_becomes_unknown_js_not_empty(self):
        html = """
        <html><body>
          <main>
            <h1>\u0420\u0435\u0441\u0442\u043e\u0440\u0430\u043d\u044b \u041e\u0440\u0441\u043a\u0430</h1>
            <div id="app">\u041c\u0435\u043d\u044e \u0438 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0435\u0434\u044b \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u044e\u0442\u0441\u044f...</div>
          </main>
        </body></html>
        """

        result = UniversalHtmlParser().parse("https://chibbis.ru/orsk/restaurants", html=html)

        self.assertEqual(result.page_structure, PageStructure.UNKNOWN_JS)
        self.assertFalse(result.success)
        self.assertEqual(result.next_strategy, "browser")

    def test_books_catalog_recognizes_real_gbp_symbol(self):
        html = """
        <html>
          <head><title>Travel | Books to Scrape</title></head>
          <body>
            <h1>Travel</h1>
            <article class="product_pod">
              <h3><a href="../../../its-only-the-himalayas_981/index.html">It's Only the Himalayas</a></h3>
              <p class="price_color">£45.17</p>
              <p class="star-rating Two">Two</p>
            </article>
            <article class="product_pod">
              <h3><a href="../../../full-moon-over-noahs-ark_811/index.html">Full Moon over Noah's Ark</a></h3>
              <p class="price_color">£49.43</p>
              <p class="star-rating Four">Four</p>
            </article>
            <article class="product_pod">
              <h3><a href="../../../see-america_732/index.html">See America</a></h3>
              <p class="price_color">£48.87</p>
              <p class="star-rating Three">Three</p>
            </article>
            <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
          </body>
        </html>
        """

        result = UniversalHtmlParser().parse(
            "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
            html=html,
        )

        self.assertEqual(result.task_type, TaskType.UNIVERSAL_CATALOG)
        self.assertEqual(result.page_structure, PageStructure.CATALOG)
        self.assertGreaterEqual(result.confidence, 0.85)
        self.assertGreaterEqual(len(result.entities), 3)
        self.assertEqual(result.entities[0].attributes["currency"], "GBP")

    def test_books_to_scrape_travel_category_is_catalog(self):
        html = """
        <html>
          <head><title>Travel | Books to Scrape</title></head>
          <body>
            <div class="page_inner">
              <section>
                <ol class="row">
                  <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                    <article class="product_pod">
                      <h3><a href="../../../its-only-the-himalayas_981/index.html">It's Only the Himalayas</a></h3>
                      <p class="price_color">£45.17</p>
                    </article>
                  </li>
                  <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                    <article class="product_pod">
                      <h3><a href="../../../full-moon-over-noahs-ark_811/index.html">Full Moon over Noah's Ark</a></h3>
                      <p class="price_color">£49.43</p>
                    </article>
                  </li>
                  <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
                    <article class="product_pod">
                      <h3><a href="../../../see-america_732/index.html">See America</a></h3>
                      <p class="price_color">£48.87</p>
                    </article>
                  </li>
                </ol>
                <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
              </section>
            </div>
          </body>
        </html>
        """

        result = UniversalHtmlParser().parse(
            "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
            html=html,
        )

        self.assertEqual(result.task_type, TaskType.UNIVERSAL_CATALOG)
        self.assertEqual(result.page_structure, PageStructure.CATALOG)
        self.assertGreaterEqual(result.confidence, 0.85)

    def test_router_runs_registered_parser(self):
        router = Router()
        router.register(TaskType.UNIVERSAL_PAGE, UniversalHtmlParser(), priority=10)

        result = router.parse(
            "https://example.com/menu",
            html="<html><body><div>Шашлык 350 ₽</div></body></html>",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.parser_chain, ["universal_html"])
        self.assertEqual(result.entities[0].title, "Шашлык")

    def test_exports_json_and_csv(self):
        result = UniversalHtmlParser().parse(
            "https://example.com/menu",
            html="<html><body><div>Шашлык 350 ₽</div></body></html>",
        )

        self.assertIn("Шашлык", export_json(result))
        rows = list(csv.DictReader(io.StringIO(export_csv(result).decode("utf-8-sig"))))
        self.assertEqual(rows[0]["title"], "Шашлык")
        self.assertEqual(rows[0]["price"], "350.0")


if __name__ == "__main__":
    unittest.main()
