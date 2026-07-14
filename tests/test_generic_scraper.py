import asyncio
import csv
import io
import unittest

from app.generic_scraper import (
    detect_next_page_url,
    discover_relevant_links,
    enrich_records_from_detail_pages,
    export_csv,
    extract_records_adaptive,
    extract_records_from_discovered_pages,
    extract_product_detail_fields,
    extract_product_records,
    fetch_page_sequence,
    normalize_fields,
    run_scraping_task,
    validate_records,
)
from app.task_intents import StructuredTask, TaskType


BOOKS_HTML = """
<html>
  <body>
    <article class="product_pod">
      <p class="star-rating Three"></p>
      <h3><a href="catalogue/a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light</a></h3>
      <div class="product_price">
        <p class="price_color">£51.77</p>
        <p class="instock availability">In stock</p>
      </div>
    </article>
    <article class="product_pod">
      <p class="star-rating One"></p>
      <h3><a href="catalogue/tipping-the-velvet_999/index.html" title="Tipping the Velvet">Tipping</a></h3>
      <div class="product_price">
        <p class="price_color">£53.74</p>
        <p class="instock availability">In stock</p>
      </div>
    </article>
  </body>
</html>
"""

BOOKS_PAGE_1 = BOOKS_HTML.replace(
    "</body>",
    '<ul class="pager"><li class="next"><a href="catalogue/page-2.html">next</a></li></ul></body>',
)

BOOKS_PAGE_2 = BOOKS_HTML.replace("A Light in the Attic", "Second Page Book").replace(
    "catalogue/a-light-in-the-attic_1000/index.html",
    "second-page-book/index.html",
)

BOOK_DETAIL_HTML = """
<html>
  <body>
    <div class="product_main">
      <p class="star-rating Four"></p>
    </div>
    <div id="product_description"><h2>Product Description</h2></div>
    <p>A sharp and quiet book description.</p>
    <table class="table table-striped">
      <tr><th>UPC</th><td>a897fe39b1053632</td></tr>
      <tr><th>Product Type</th><td>Books</td></tr>
      <tr><th>Price (excl. tax)</th><td>ВЈ51.77</td></tr>
      <tr><th>Price (incl. tax)</th><td>ВЈ51.77</td></tr>
      <tr><th>Tax</th><td>ВЈ0.00</td></tr>
      <tr><th>Availability</th><td>In stock (22 available)</td></tr>
      <tr><th>Number of reviews</th><td>0</td></tr>
    </table>
  </body>
</html>
"""


class GenericScraperTests(unittest.TestCase):
    def test_extracts_books_to_scrape_product_cards(self):
        records = extract_product_records(
            BOOKS_HTML,
            "https://books.toscrape.com/",
            ["title", "price", "availability", "rating", "product_url"],
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "A Light in the Attic")
        self.assertEqual(records[0]["price"], "£51.77")
        self.assertEqual(records[0]["availability"], "In stock")
        self.assertEqual(records[0]["rating"], "Three")
        self.assertEqual(
            records[0]["product_url"],
            "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        )

    def test_csv_export_preserves_requested_field_order(self):
        fields = ["title", "price", "availability", "rating", "product_url"]
        records = extract_product_records(BOOKS_HTML, "https://books.toscrape.com/", fields)

        data = export_csv(records, fields).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(data)))

        self.assertEqual(list(rows[0].keys()), fields)
        self.assertEqual(rows[1]["title"], "Tipping the Velvet")

    def test_validation_rejects_missing_required_field(self):
        report = validate_records([{"title": "Only title", "price": ""}], ["title", "price"])

        self.assertFalse(report.ok)
        self.assertIn("Field 'price' is empty for all records.", report.warnings)

    def test_normalizes_url_and_name_aliases(self):
        self.assertEqual(normalize_fields(["name", "url", "price"]), ["title", "product_url", "price"])

    def test_normalizes_books_detail_fields(self):
        self.assertEqual(
            normalize_fields(["UPC", "product_type", "tax", "number_of_reviews", "description"]),
            ["upc", "product_type", "tax", "number_of_reviews", "description"],
        )

    def test_extracts_books_to_scrape_detail_fields(self):
        details = extract_product_detail_fields(BOOK_DETAIL_HTML)

        self.assertEqual(details["upc"], "a897fe39b1053632")
        self.assertEqual(details["product_type"], "Books")
        self.assertEqual(details["tax"], "ВЈ0.00")
        self.assertEqual(details["number_of_reviews"], "0")
        self.assertEqual(details["description"], "A sharp and quiet book description.")

    def test_enriches_product_records_from_detail_pages(self):
        records = extract_product_records(
            BOOKS_HTML,
            "https://books.toscrape.com/",
            ["title", "product_url", "upc", "product_type", "tax", "number_of_reviews", "description"],
        )

        async def fake_fetcher(url):
            return 200, BOOK_DETAIL_HTML

        asyncio.run(
            enrich_records_from_detail_pages(
                records,
                ["upc", "product_type", "tax", "number_of_reviews", "description"],
                fetcher=fake_fetcher,
            )
        )

        self.assertEqual(records[0]["upc"], "a897fe39b1053632")
        self.assertEqual(records[0]["product_type"], "Books")
        self.assertEqual(records[0]["tax"], "ВЈ0.00")
        self.assertEqual(records[0]["number_of_reviews"], "0")
        self.assertEqual(records[0]["description"], "A sharp and quiet book description.")

    def test_detects_books_to_scrape_next_page_url(self):
        self.assertEqual(
            detect_next_page_url(BOOKS_PAGE_1, "https://books.toscrape.com/"),
            "https://books.toscrape.com/catalogue/page-2.html",
        )

    def test_fetch_page_sequence_follows_next_links(self):
        async def fake_fetcher(url):
            pages = {
                "https://books.toscrape.com/": BOOKS_PAGE_1,
                "https://books.toscrape.com/catalogue/page-2.html": BOOKS_PAGE_2,
            }
            return 200, pages[url]

        pages = asyncio.run(
            fetch_page_sequence(
                "https://books.toscrape.com/",
                follow_pagination=True,
                max_pages=5,
                fetcher=fake_fetcher,
            )
        )

        self.assertEqual([page.url for page in pages], [
            "https://books.toscrape.com/",
            "https://books.toscrape.com/catalogue/page-2.html",
        ])

    def test_adaptive_extraction_falls_back_to_price_entities(self):
        html = """
        <html>
          <body>
            <h1>Меню</h1>
            <div>Шашлык из свинины 350 ₽</div>
            <div>Салат овощной 180 ₽</div>
          </body>
        </html>
        """

        records = extract_records_adaptive(
            html,
            "https://example.com/menu",
            ["title", "price", "description", "product_url"],
            focus_terms=["шашлык"],
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Шашлык из свинины")
        self.assertEqual(records[0]["price"], "350")
        self.assertEqual(records[0]["product_url"], "https://example.com/menu")

    def test_discovers_relevant_menu_links_for_focus_terms(self):
        html = """
        <html>
          <body>
            <a href="/orsk/restaurants/kebab-house">Шашлычная у мангала</a>
            <a href="https://external.example/menu">External</a>
          </body>
        </html>
        """

        links = discover_relevant_links(
            html,
            "https://chibbis.ru/orsk/restaurants",
            focus_terms=["шашлык"],
        )

        self.assertEqual(links, ["https://chibbis.ru/orsk/restaurants/kebab-house"])

    def test_discovered_pages_are_parsed_with_universal_fallback(self):
        from app.generic_scraper import PageFetch

        start_html = """
        <html>
          <body><a href="/menu/shashlyk">Шашлык и мясные блюда</a></body>
        </html>
        """
        detail_html = """
        <html>
          <body>
            <div>Шашлык из баранины 450 ₽ 250 г</div>
            <div>Люля-кебаб 390 ₽</div>
          </body>
        </html>
        """

        async def fake_fetcher(url):
            return 200, detail_html

        records = asyncio.run(
            extract_records_from_discovered_pages(
                [PageFetch("https://example.com/restaurants", 200, start_html)],
                ["title", "price", "description", "product_url"],
                focus_terms=["шашлык", "мяс"],
                fetcher=fake_fetcher,
            )
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Шашлык из баранины")
        self.assertEqual(records[0]["price"], "450")
        self.assertEqual(records[1]["title"], "Люля-кебаб")


    def test_run_scraping_task_uses_browser_fetcher_when_requested(self):
        import app.generic_scraper as scraper_module

        calls = []

        async def fake_browser_fetcher(url):
            calls.append(url)
            return 200, BOOKS_HTML

        task = StructuredTask(
            TaskType.SCRAPING,
            raw_text="scrape rendered catalog",
            target_url="https://example.com/catalog",
            fields=["title", "price", "availability", "rating", "product_url"],
            output="csv",
            parameters={"browser_fallback": True},
        )

        async def run():
            with unittest.mock.patch.object(scraper_module, "fetch_html_browser", fake_browser_fetcher):
                return await run_scraping_task(task)

        result = asyncio.run(run())

        self.assertEqual(calls, ["https://example.com/catalog"])
        self.assertEqual(result.metrics.records, 2)
        self.assertEqual(result.metrics.http_status, 200)


if __name__ == "__main__":
    unittest.main()
