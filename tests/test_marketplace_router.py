"""Marketplace router regression tests."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_ozon_search_price_does_not_claim_product_is_in_stock():
    from app.parsers.router import search_all_marketplaces

    with patch(
        "app.parsers.router.search_ozon",
        new=AsyncMock(
            return_value=[
                {
                    "name": "Термокружка",
                    "price": 1299,
                    "url": "https://www.ozon.ru/product/test",
                }
            ]
        ),
    ):
        results = await search_all_marketplaces(
            "термокружка",
            max_per_site=1,
            exclude_marketplaces=("wildberries", "yandex_market"),
        )

    assert len(results["ozon"]) == 1
    assert results["ozon"][0].price == 1299
    assert results["ozon"][0].availability == "unknown"
