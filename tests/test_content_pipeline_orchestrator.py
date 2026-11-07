"""Integration test for the full Content Intelligence Pipeline orchestrator."""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime

from tests.content_pipeline_fakes import ScriptedAIProvider
from tests.helpers import reload_app_modules

_STRATEGY_PAYLOAD = {
    "target_audience": "Путешественники",
    "usage_scenarios": ["в дороге", "в офисе"],
    "key_need": "Держать напитки горячими",
    "key_selling_proposition": "Держит температуру 12 часов",
    "secondary_benefits": ["компактная"],
    "objections": ["дорого"],
    "objection_responses": ["окупается долговечностью"],
    "tone_of_voice": "уверенный",
    "description_structure": ["назначение", "особенности"],
    "priority_attributes": ["Материал"],
    "forbidden_claims": ["вечная гарантия"],
    "formality_level": "professional",
}

_TITLE_PAYLOAD = {
    "title": "Термокружка Stanley 500 мл нержавеющая сталь",
    "alternatives": ["Вариант 2", "Вариант 3", "Вариант 4", "Вариант 5"],
    "used_keywords": ["термокружка", "stanley"],
    "reasoning": "включили primary keys",
    "confidence": 0.9,
}

_BENEFITS_PAYLOAD = {
    "bullets": ["Сталь -> прочность -> не деформируется при падении"],
    "infographic_bullets": ["Прочная сталь"],
    "description_bullets": ["Корпус из нержавеющей стали устойчив к деформации"],
    "objection_counters": ["Окупается за счёт долговечности"],
    "reasoning": "",
    "confidence": 0.85,
}

_DESCRIPTION_PAYLOAD = {
    "short_description": "Термокружка Stanley для тепла в дороге",
    "full_description": "Термокружка Stanley из нержавеющей стали объёмом 500 мл. Вес 450 г.",
    "blocks": {"назначение": "путешествия"},
    "used_keywords": ["500мл"],
    "reasoning": "",
    "confidence": 0.8,
}


class ContentPipelineOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.content_pipeline.artifact_store import ArtifactStore
        from app.database import Database, Product
        from app.products.schema import UnifiedProduct
        from app.projects.service import ProjectService

        self.db = Database()
        await self.db.init()
        self.ArtifactStore = ArtifactStore
        self.artifact_store = ArtifactStore(self.db)
        self.queue = DatabaseApprovalQueue(self.db)

        async with self.db.session() as session:
            product = Product(
                url_hash="hash-1",
                url="https://example.test/products/1",
                name="Термокружка",
                first_seen=datetime.now(UTC),
                last_check=datetime.now(UTC),
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            self.product_id = product.id

        project_service = ProjectService(self.db)
        self.project = await project_service.create_project(name="Тест", marketplace="ozon")

        unified = UnifiedProduct(
            name="Термокружка Stanley 500 мл",
            source_id="sku-1",
            source_type="ozon",
            brand="Stanley",
            category="Термокружки",
            attributes={"Материал": "Нержавеющая сталь"},
            weight_g=450,
            marketplace="ozon",
        )

        async with self.db.session() as session:
            product_obj = await session.get(Product, self.product_id)
            self.project_product, _ = await project_service.link_imported_product(
                self.project.project_id, product_obj, unified
            )

    async def asyncTearDown(self):
        await self.db._engine.dispose()

    async def _run(self):
        from app.content_pipeline.pipeline import run_content_pipeline

        provider = ScriptedAIProvider(
            [
                json.dumps(_STRATEGY_PAYLOAD, ensure_ascii=False),
                json.dumps(_TITLE_PAYLOAD, ensure_ascii=False),
                json.dumps(_BENEFITS_PAYLOAD, ensure_ascii=False),
                json.dumps(_DESCRIPTION_PAYLOAD, ensure_ascii=False),
            ]
        )
        result = await run_content_pipeline(
            self.db,
            project_id=self.project.project_id,
            product_id=self.product_id,
            provider=provider,
            job_id="job-1",
        )
        return result, provider

    async def test_full_pipeline_produces_quality_report_and_suggestions(self):
        result, provider = await self._run()

        self.assertEqual(len(provider.calls), 4)
        self.assertTrue(0 <= result.quality_report.cqi <= 100)
        self.assertEqual(len(result.approval_ids), 3)
        self.assertFalse(result.fact_check_contradicted)

    async def test_artifacts_are_saved_for_each_stage(self):
        await self._run()

        for artifact_type in ("content_strategy", "semantic_plan", "fact_check_report", "quality_report"):
            latest = await self.artifact_store.get_latest(
                project_id=self.project.project_id,
                project_product_id=self.project_product.project_product_id,
                artifact_type=artifact_type,
            )
            self.assertIsNotNone(latest, f"missing artifact {artifact_type}")

    async def test_suggestions_have_expected_fields_and_metadata(self):
        await self._run()

        all_items = await self.queue.get_all()
        fields = {item.suggestion.field for item in all_items}
        self.assertEqual(fields, {"title", "description", "selling_points"})
        for item in all_items:
            self.assertEqual(item.suggestion.metadata["project_id"], self.project.project_id)
            self.assertEqual(item.suggestion.metadata["source"], "content_pipeline")
            self.assertIn("prompt_id", item.suggestion.metadata)

        title_item = next(i for i in all_items if i.suggestion.field == "title")
        self.assertEqual(title_item.suggestion.after, _TITLE_PAYLOAD["title"])

    async def test_pipeline_picks_up_existing_competitor_batch(self):
        from app.competitor_analysis.store import CompetitorSnapshotStore
        from app.parsers.base import ProductData

        store = CompetitorSnapshotStore(self.db)
        await store.save_batch(
            project_id=self.project.project_id,
            project_product_id=self.project_product.project_product_id,
            product_id=self.product_id,
            search_query="Термокружка Stanley 500 мл",
            products=[
                (
                    "wildberries",
                    ProductData(
                        name="Термокружка Contigo вакуумная спортивная 500мл",
                        price=1200,
                        old_price=None,
                        discount_pct=None,
                        availability="in_stock",
                        url="https://www.wildberries.ru/catalog/1/detail.aspx",
                        image_url=None,
                        marketplace="wildberries",
                    ),
                ),
                (
                    "wildberries",
                    ProductData(
                        name="Термос Contigo вакуумный для спорта",
                        price=1150,
                        old_price=None,
                        discount_pct=None,
                        availability="in_stock",
                        url="https://www.wildberries.ru/catalog/2/detail.aspx",
                        image_url=None,
                        marketplace="wildberries",
                    ),
                ),
            ],
        )

        await self._run()

        semantic_artifact = await self.artifact_store.get_latest(
            project_id=self.project.project_id,
            project_product_id=self.project_product.project_product_id,
            artifact_type="semantic_plan",
        )
        payload = self.artifact_store.payload_dict(semantic_artifact)
        self.assertIn("contigo", payload["competitor_gap_terms"])

    async def test_pipeline_works_without_any_competitor_batch(self):
        # Ничего не ломается, если конкурентный анализ ещё не запускался
        result, _ = await self._run()
        self.assertEqual(len(result.approval_ids), 3)

    async def test_contradicted_fact_flags_metadata_but_still_queues(self):
        # Вес в сгенерированном описании (900 г) противоречит паспорту (450 г из UnifiedProduct)
        bad_description = dict(_DESCRIPTION_PAYLOAD)
        bad_description["full_description"] = "Термокружка весом 900 г из стали."

        from app.content_pipeline.pipeline import run_content_pipeline

        provider = ScriptedAIProvider(
            [
                json.dumps(_STRATEGY_PAYLOAD, ensure_ascii=False),
                json.dumps(_TITLE_PAYLOAD, ensure_ascii=False),
                json.dumps(_BENEFITS_PAYLOAD, ensure_ascii=False),
                json.dumps(bad_description, ensure_ascii=False),
            ]
        )
        result = await run_content_pipeline(
            self.db,
            project_id=self.project.project_id,
            product_id=self.product_id,
            provider=provider,
            job_id="job-2",
        )
        self.assertTrue(result.fact_check_contradicted)
        # предложение всё равно ставится в очередь — оператор решает при approve
        self.assertEqual(len(result.approval_ids), 3)


if __name__ == "__main__":
    unittest.main()
