"""Tests for CompetitorAnalysisService — search_all_marketplaces and
WildberriesParser._fetch_reviews are mocked, no real network calls."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch


class CompetitorAnalysisServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        from tests.helpers import reload_app_modules

        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.competitor_analysis.store import CompetitorSnapshotStore
        from app.database import Database, Product
        from app.products.schema import UnifiedProduct
        from app.projects.service import ProjectService

        self.db = Database()
        await self.db.init()
        self.store = CompetitorSnapshotStore(self.db)

        async with self.db.session() as session:
            product = Product(
                url_hash="hash-svc-1",
                url="https://example.test/products/svc-1",
                name="Термокружка",
                first_seen=datetime.now(UTC),
                last_check=datetime.now(UTC),
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            self.product_id = product.id

        project_service = ProjectService(self.db)
        self.project = await project_service.create_project(name="Тест сервиса", marketplace="ozon")

        unified = UnifiedProduct(
            name="Термокружка Stanley 500 мл",
            source_id="sku-svc-1",
            source_type="ozon",
            brand="Stanley",
            marketplace="ozon",
        )
        async with self.db.session() as session:
            product_obj = await session.get(Product, self.product_id)
            self.project_product, _ = await project_service.link_imported_product(
                self.project.project_id, product_obj, unified
            )

    async def asyncTearDown(self):
        await self.db._engine.dispose()

    def _wb_product(self, name, url):
        from app.parsers.base import ProductData

        return ProductData(
            name=name, price=1000, old_price=None, discount_pct=None, availability="in_stock",
            url=url, image_url=None, rating=4.7, reviews_count=100, marketplace="wildberries",
        )

    def _ozon_product(self, name):
        from app.parsers.base import ProductData

        return ProductData(
            name=name, price=1100, old_price=None, discount_pct=None, availability="in_stock",
            url="https://ozon.ru/product/1", image_url=None, marketplace="ozon",
        )

    async def test_refresh_saves_batch_across_marketplaces(self):
        from app.competitor_analysis.service import CompetitorAnalysisService

        search_results = {
            "wildberries": [
                self._wb_product("Термокружка WB конкурент", "https://www.wildberries.ru/catalog/111222333/detail.aspx"),
            ],
            "ozon": [self._ozon_product("Термокружка Ozon конкурент")],
        }

        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value=search_results),
        ) as mock_search, patch(
            "app.competitor_analysis.service.WildberriesParser._fetch_reviews",
            new=AsyncMock(return_value=["Отличный товар", "Держит тепло весь день"]),
        ) as mock_reviews:
            service = CompetitorAnalysisService(self.db)
            batch_id, records = await service.refresh_competitors(self.project.project_id, self.product_id)

        self.assertEqual(len(records), 2)
        mock_search.assert_awaited_once()
        called_query = mock_search.await_args.args[0]
        self.assertEqual(called_query, "Термокружка Stanley 500 мл")

        mock_reviews.assert_awaited_once()
        called_nm_id = mock_reviews.await_args.args[1]
        self.assertEqual(called_nm_id, 111222333)

        latest = await self.store.get_latest_batch(
            project_id=self.project.project_id, project_product_id=self.project_product.project_product_id
        )
        self.assertEqual({r.batch_id for r in latest}, {batch_id})
        wb_record = next(r for r in latest if r.marketplace == "wildberries")
        self.assertEqual(
            self.store.reviews_of(wb_record), ["Отличный товар", "Держит тепло весь день"]
        )
        ozon_record = next(r for r in latest if r.marketplace == "ozon")
        self.assertEqual(self.store.reviews_of(ozon_record), [])

    async def test_reviews_not_fetched_beyond_limit(self):
        from app.competitor_analysis.service import CompetitorAnalysisService

        wb_products = [
            self._wb_product(f"Термокружка WB {i}", f"https://www.wildberries.ru/catalog/{100000 + i}/detail.aspx")
            for i in range(5)
        ]
        search_results = {"wildberries": wb_products, "ozon": []}

        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value=search_results),
        ), patch(
            "app.competitor_analysis.service.WildberriesParser._fetch_reviews",
            new=AsyncMock(return_value=["отзыв"]),
        ) as mock_reviews:
            service = CompetitorAnalysisService(self.db)
            await service.refresh_competitors(self.project.project_id, self.product_id)

        self.assertEqual(mock_reviews.await_count, 3)  # _MAX_WB_REVIEWS_FETCHED

    async def test_ozon_review_signals_are_enriched_for_top_competitors(self):
        from app.competitor_analysis.service import CompetitorAnalysisService

        ozon_products = [self._ozon_product(f"Термокружка Ozon {i}") for i in range(3)]
        search_results = {"wildberries": [], "ozon": ozon_products, "yandex_market": []}
        api_payload = {
            "name": "Термокружка",
            "price": 1100,
            "availability": "unknown",
            "rating": 4.8,
            "reviews_count": 153,
            "reviews": ["Хорошо держит тепло", "Удобная крышка"],
        }

        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value=search_results),
        ), patch(
            "app.parsers.ozon.OzonParser._fetch_api_data",
            new=AsyncMock(return_value=api_payload),
        ) as mock_api:
            service = CompetitorAnalysisService(self.db)
            _, records = await service.refresh_competitors(self.project.project_id, self.product_id)

        self.assertEqual(mock_api.await_count, 2)
        ozon_records = [r for r in records if r.marketplace == "ozon"]
        self.assertEqual(ozon_records[0].rating, 4.8)
        self.assertEqual(ozon_records[0].reviews_count, 153)
        self.assertEqual(
            self.store.reviews_of(ozon_records[0]),
            ["Хорошо держит тепло", "Удобная крышка"],
        )
        self.assertIsNone(ozon_records[2].rating)
        self.assertEqual(self.store.reviews_of(ozon_records[2]), [])

    async def test_no_wb_results_skips_review_fetch(self):
        from app.competitor_analysis.service import CompetitorAnalysisService

        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value={"wildberries": [], "ozon": [self._ozon_product("Термокружка X")]}),
        ), patch(
            "app.competitor_analysis.service.WildberriesParser._fetch_reviews",
            new=AsyncMock(return_value=["отзыв"]),
        ) as mock_reviews:
            service = CompetitorAnalysisService(self.db)
            _, records = await service.refresh_competitors(self.project.project_id, self.product_id)

        mock_reviews.assert_not_awaited()
        self.assertEqual(len(records), 1)

    async def test_refresh_drops_brand_collision_but_keeps_relevant_competitor(self):
        """Regression for COMPETITOR-UNFILTERED: search_all_marketplaces()
        results were saved unfiltered -- a marketplace hit matching only the
        product's brand name (not what the product actually is) could end
        up saved as a "competitor" for a completely unrelated product,
        exactly the class of bug already fixed once for card_filler.py
        (D31). The product under test is "Термокружка Stanley 500 мл"
        (brand Stanley); an unrelated "Stanley" product must be dropped,
        while an actual thermal-mug competitor must be kept."""
        from app.competitor_analysis.service import CompetitorAnalysisService

        irrelevant = self._ozon_product("Отвертка Stanley набор 6 предметов")
        relevant = self._wb_product(
            "Термокружка Stanley Classic 470 мл", "https://www.wildberries.ru/catalog/222333444/detail.aspx"
        )

        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value={"wildberries": [relevant], "ozon": [irrelevant]}),
        ), patch(
            "app.competitor_analysis.service.WildberriesParser._fetch_reviews",
            new=AsyncMock(return_value=[]),
        ):
            service = CompetitorAnalysisService(self.db)
            _, records = await service.refresh_competitors(self.project.project_id, self.product_id)

        names = {r.competitor_name for r in records}
        self.assertIn("Термокружка Stanley Classic 470 мл", names)
        self.assertNotIn("Отвертка Stanley набор 6 предметов", names)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
