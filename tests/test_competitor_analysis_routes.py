"""HTTP-level tests for Competitor Analysis routes."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient


class CompetitorAnalysisRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        from tests.helpers import reload_app_modules

        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.database import Database, Product
        from app.products.schema import UnifiedProduct
        from app.projects.service import ProjectService
        from app.web.app import create_app

        self.db = Database()
        await self.db.init()
        self.queue = DatabaseApprovalQueue(self.db)

        async with self.db.session() as session:
            product = Product(
                url_hash="hash-routes-comp-1",
                url="https://example.test/products/routes-comp-1",
                name="Термокружка",
                first_seen=datetime.now(UTC),
                last_check=datetime.now(UTC),
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            self.product_id = product.id

        project_service = ProjectService(self.db)
        self.project = await project_service.create_project(name="Тест роутов конкурентов", marketplace="ozon")

        unified = UnifiedProduct(
            name="Термокружка Stanley 500 мл", source_id="sku-comp-1", source_type="ozon", marketplace="ozon",
        )
        async with self.db.session() as session:
            product_obj = await session.get(Product, self.product_id)
            await project_service.link_imported_product(self.project.project_id, product_obj, unified)

        self.app = create_app()
        self.app.state.db = self.db
        self.app.state.ai_queue = self.queue
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()

    def _wb_product(self, name, url):
        from app.parsers.base import ProductData

        return ProductData(
            name=name, price=1000, old_price=None, discount_pct=None, availability="in_stock",
            url=url, image_url=None, rating=4.5, reviews_count=10, marketplace="wildberries",
        )

    async def test_competitors_404_before_refresh(self):
        resp = await self.client.get(
            f"/api/projects/{self.project.project_id}/products/{self.product_id}/competitors"
        )
        self.assertEqual(resp.status_code, 404)

    async def test_refresh_unknown_product_404(self):
        resp = await self.client.post(
            f"/api/projects/{self.project.project_id}/products/999999/competitors/refresh"
        )
        self.assertEqual(resp.status_code, 404)

    async def test_full_refresh_then_get_competitors_and_job(self):
        search_results = {
            "wildberries": [
                self._wb_product("WB Конкурент", "https://www.wildberries.ru/catalog/555666777/detail.aspx"),
            ],
            "ozon": [],
        }
        with patch(
            "app.competitor_analysis.service.search_all_marketplaces",
            new=AsyncMock(return_value=search_results),
        ), patch(
            "app.competitor_analysis.service.WildberriesParser._fetch_reviews",
            new=AsyncMock(return_value=["Хорошо держит тепло"]),
        ):
            run_resp = await self.client.post(
                f"/api/projects/{self.project.project_id}/products/{self.product_id}/competitors/refresh"
            )
            self.assertEqual(run_resp.status_code, 200)
            job_id = run_resp.json()["job_id"]

            job_resp = await self.client.get(f"/api/competitor-analysis/jobs/{job_id}")
            self.assertEqual(job_resp.status_code, 200)
            self.assertEqual(job_resp.json()["status"], "succeeded")

        resp = await self.client.get(
            f"/api/projects/{self.project.project_id}/products/{self.product_id}/competitors"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["competitors"]), 1)
        self.assertEqual(data["competitors"][0]["reviews"], ["Хорошо держит тепло"])
        self.assertEqual(data["aggregates"]["count"], 1)

        history_resp = await self.client.get(
            f"/api/projects/{self.project.project_id}/products/{self.product_id}/competitors/history"
        )
        self.assertEqual(len(history_resp.json()), 1)

    async def test_detail_page_renders_competitors_section(self):
        resp = await self.client.get(f"/projects/{self.project.project_id}/products/{self.product_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Найти конкурентов", resp.text)


if __name__ == "__main__":
    unittest.main()
