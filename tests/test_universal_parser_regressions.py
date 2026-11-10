import asyncio

import pytest

from app.parsers.universal import UniversalParser, _parse_int_price


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 299 ₽", 1299),
        ("1\u00a0299 ₽", 1299),
        ("1,299.00", 1299),
        ("1.299,00", 1299),
        ("1299,00", 1299),
        ("1299.00", 1299),
        ("350", 350),
        ("0", None),
        ("", None),
        ("not a price", None),
    ],
)
def test_parse_int_price_localized_formats(raw, expected):
    assert _parse_int_price(raw) == expected


def test_universal_parser_reads_product_from_json_ld_graph():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@graph": [
          {"@type": "Organization", "name": "Example"},
          {
            "@type": "Product",
            "name": "Кофемолка Example",
            "description": "Стальная кофемолка",
            "image": [{"url": "https://example.com/product.jpg"}],
            "offers": {
              "@type": "Offer",
              "price": "1 299,00",
              "highPrice": "1 599,00",
              "availability": "https://schema.org/InStock"
            }
          }
        ]
      }
      </script>
    </head><body><main>Карточка товара</main></body></html>
    """
    result = asyncio.run(UniversalParser().fetch_product("https://example.com/item", html))

    assert result.success
    assert result.data is not None
    assert result.data.name == "Кофемолка Example"
    assert result.data.price == 1299
    assert result.data.old_price == 1599
    assert result.data.discount_pct == 19
    assert result.data.image_url == "https://example.com/product.jpg"
    assert result.data.availability == "in_stock"


def test_universal_parser_ignores_malformed_json_ld_and_uses_open_graph():
    html = """
    <html><head>
      <script type="application/ld+json">{broken json</script>
      <meta property="og:title" content="Наушники Example">
      <meta property="og:image" content="https://example.com/headphones.jpg">
      <meta property="og:description" content="Беспроводные наушники">
    </head><body><main>Описание товара</main></body></html>
    """
    result = asyncio.run(UniversalParser().fetch_product("https://example.com/headphones", html))

    assert result.success
    assert result.data is not None
    assert result.data.name == "Наушники Example"
    assert result.data.image_url == "https://example.com/headphones.jpg"


def test_universal_parser_does_not_mark_content_without_div_as_empty():
    html = """
    <html><body>
      <main><h1>Смартфон Example</h1><p>Цена 12 990 ₽</p></main>
    </body></html>
    """
    result = asyncio.run(UniversalParser().fetch_product("https://example.com/phone", html))

    assert result.success
    assert result.data is not None
    assert result.data.name == "Смартфон Example"
    assert result.data.price == 12990


def test_universal_parser_empty_and_loading_pages_request_browser_fallback():
    parser = UniversalParser()
    for html in ("", "<html><body></body></html>", "<html><body><div>Загрузка...</div></body></html>"):
        result = asyncio.run(parser.fetch_product("https://example.com/item", html))
        assert not result.success
        assert result.data is None
        assert result.next_strategy == "browser"
