"""HTTP-level tests for Content Intelligence Pipeline routes."""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from tests.content_pipeline_fakes import ScriptedAIProvider
from tests.helpers import reload_app_modules
from tests.test_content_pipeline_orchestrator import (
    _BENEFITS_PAYLOAD,
    _DESCRIPTION_PAYLOAD,
    _STRATEGY_PAYLOAD,
    _TITLE_PAYLOAD,
)


class ContentPipelineRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
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
                url_hash="hash-routes-1",
                url="https://example.test/products/routes-1",
                name="Термокружка",
                first_seen=datetime.now(UTC),
                last_check=datetime.now(UTC),
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            self.product_id = product.id

        project_service = ProjectService(self.db)
        self.project = await project_service.create_project(name="Тест роутов", marketplace="ozon")

        unified = UnifiedProduct(
            name="Термокружка Stanley 500 мл",
            source_id="sku-routes-1",
            source_type="ozon",
            brand="Stanley",
            attributes={"Материал": "Нержавеющая сталь"},
            marketplace="ozon",
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

    async def test_run_returns_404_for_unknown_product(self):
        resp = await self.client.post(
            f"/api/projects/{self.project.project_id}/products/999999/content-pipeline/run"
        )
        self.assertEqual(resp.status_code, 404)

    async def test_artifact_routes_404_before_pipeline_runs(self):
        resp = await self.client.get(
            f"/api/projects/{self.project.project_id}/products/{self.product_id}/content-strategy"
        )
        self.assertEqual(resp.status_code, 404)

    async def test_full_run_then_artifacts_and_job_and_suggestions(self):
        provider = ScriptedAIProvider(
            [
                json.dumps(_STRATEGY_PAYLOAD, ensure_ascii=False),
                json.dumps(_TITLE_PAYLOAD, ensure_ascii=False),
                json.dumps(_BENEFITS_PAYLOAD, ensure_ascii=False),
                json.dumps(_DESCRIPTION_PAYLOAD, ensure_ascii=False),
            ]
        )
        with patch("app.content_pipeline.pipeline.create_configured_provider", return_value=provider):
            run_resp = await self.client.post(
                f"/api/projects/{self.project.project_id}/products/{self.product_id}/content-pipeline/run"
            )
            self.assertEqual(run_resp.status_code, 200)
            job_id = run_resp.json()["job_id"]

            job_resp = await self.client.get(f"/api/content-pipeline/jobs/{job_id}")
            self.assertEqual(job_resp.status_code, 200)
            self.assertEqual(job_resp.json()["status"], "succeeded")

        for route_suffix in ("content-strategy", "semantic-plan", "fact-check", "quality-report"):
            resp = await self.client.get(
                f"/api/projects/{self.project.project_id}/products/{self.product_id}/{route_suffix}"
            )
            self.assertEqual(resp.status_code, 200, f"{route_suffix} should be available after run")
            self.assertIn("payload", resp.json())

        strategy_resp = await self.client.get(
            f"/api/projects/{self.project.project_id}/products/{self.product_id}/content-strategy"
        )
        self.assertEqual(strategy_resp.json()["payload"]["target_audience"], "Путешественники")

        suggestions_resp = await self.client.get("/api/suggestions")
        fields = {item["field"] for item in suggestions_resp.json()}
        self.assertEqual(fields, {"title", "description", "selling_points"})

    async def test_job_not_found_returns_404(self):
        resp = await self.client.get("/api/content-pipeline/jobs/does-not-exist")
        self.assertEqual(resp.status_code, 404)

    async def test_product_detail_page_renders_without_pipeline_artifacts(self):
        resp = await self.client.get(f"/projects/{self.project.project_id}/products/{self.product_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Content Intelligence Pipeline", resp.text)
        self.assertIn("Запустить Content Pipeline", resp.text)

    async def test_product_detail_page_renders_cqi_after_run(self):
        provider = ScriptedAIProvider(
            [
                json.dumps(_STRATEGY_PAYLOAD, ensure_ascii=False),
                json.dumps(_TITLE_PAYLOAD, ensure_ascii=False),
                json.dumps(_BENEFITS_PAYLOAD, ensure_ascii=False),
                json.dumps(_DESCRIPTION_PAYLOAD, ensure_ascii=False),
            ]
        )
        with patch("app.content_pipeline.pipeline.create_configured_provider", return_value=provider):
            html_run_resp = await self.client.post(
                f"/projects/{self.project.project_id}/products/{self.product_id}/content-pipeline/run"
            )
            self.assertEqual(html_run_resp.status_code, 303)

        resp = await self.client.get(f"/projects/{self.project.project_id}/products/{self.product_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("CQI", resp.text)
        self.assertIn("Перегенерировать", resp.text)


if __name__ == "__main__":
    unittest.main()
