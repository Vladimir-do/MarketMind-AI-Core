from unittest.mock import AsyncMock, patch

import pytest

from app.parsers.alt_sources import (
    find_ozon_alternative_candidates,
    score_alternative_product_match,
)
from app.parsers.base import ProductData


def test_alternative_match_requires_brand_ingredient_form_and_pack_count():
    source = "kompleks-vitaminov-gruppy-b-magniy-immunit-shipuchie-tabletki-20-sht"
    exact = score_alternative_product_match(source, "Магний В6, B6 Immunit, шипучие таблетки 20 штук")
    wrong_form = score_alternative_product_match(source, "Магний + витамины группы B Immunit капсулы 60 шт.")
    wrong_ingredient = score_alternative_product_match(source, "Витамин C Immunit шипучие таблетки 20 штук")
    assert exact["is_exact_match"] is False
    assert exact["is_strong_match"] is True
    assert exact["confidence"] == 0.90
    assert wrong_form["is_exact_match"] is False
    assert wrong_ingredient["is_exact_match"] is False


@pytest.mark.asyncio
async def test_ozon_alternative_candidates_keep_yandex_as_reference_offer():
    product = ProductData(
        name="Магний В6, B6 Immunit, шипучие таблетки 20 штук",
        price=277,
        old_price=None,
        discount_pct=None,
        availability="in_stock",
        url="https://market.yandex.ru/product--magnii-b6/123",
        image_url="https://cdn.example/item.webp",
        marketplace="yandex_market",
    )
    with patch(
        "app.parsers.yandex_market.YandexMarketParser.search",
        new=AsyncMock(return_value=[product]),
    ):
        candidates = await find_ozon_alternative_candidates(
            "https://www.ozon.ru/product/kompleks-vitaminov-gruppy-b-magniy-immunit-shipuchie-tabletki-20-sht-823223431/"
        )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["role"] == "reference_offer"
    assert candidate["source_marketplace"] == "yandex_market"
    assert candidate["is_exact_match"] is False
    assert candidate["is_strong_match"] is True
    assert candidate["field_sources"]["price"]["source_url"] == product.url
