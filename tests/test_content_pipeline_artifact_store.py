"""Tests for ArtifactStore (content_pipeline_artifacts CRUD + versioning)."""

from __future__ import annotations

import os
import unittest

from tests.helpers import reload_app_modules


class ArtifactStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.content_pipeline.artifact_store import ArtifactStore
        from app.content_pipeline.schemas import SemanticPlan
        from app.database import Database

        self.db = Database()
        await self.db.init()
        self.store = ArtifactStore(self.db)
        self.SemanticPlan = SemanticPlan

    async def asyncTearDown(self):
        await self.db._engine.dispose()

    async def test_save_and_get_latest(self):
        payload = self.SemanticPlan(title_terms=["термокружка"])
        record = await self.store.save_artifact(
            project_id="proj-1",
            project_product_id="pp-1",
            product_id=1,
            artifact_type="semantic_plan",
            payload=payload,
        )
        self.assertEqual(record.version_number, 1)

        latest = await self.store.get_latest(
            project_id="proj-1", project_product_id="pp-1", artifact_type="semantic_plan"
        )
        self.assertIsNotNone(latest)
        self.assertEqual(self.store.payload_dict(latest)["title_terms"], ["термокружка"])

    async def test_versions_increment_per_artifact_type(self):
        payload = self.SemanticPlan()
        await self.store.save_artifact(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            artifact_type="semantic_plan", payload=payload,
        )
        second = await self.store.save_artifact(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            artifact_type="semantic_plan", payload=payload,
        )
        self.assertEqual(second.version_number, 2)

        history = await self.store.list_history(
            project_id="proj-1", project_product_id="pp-1", artifact_type="semantic_plan"
        )
        self.assertEqual([h.version_number for h in history], [2, 1])

    async def test_different_artifact_types_version_independently(self):
        payload = self.SemanticPlan()
        await self.store.save_artifact(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            artifact_type="semantic_plan", payload=payload,
        )
        other = await self.store.save_artifact(
            project_id="proj-1", project_product_id="pp-1", product_id=1,
            artifact_type="fact_check_report", payload=payload,
        )
        self.assertEqual(other.version_number, 1)

    async def test_get_latest_returns_none_when_absent(self):
        latest = await self.store.get_latest(
            project_id="proj-x", project_product_id="pp-x", artifact_type="semantic_plan"
        )
        self.assertIsNone(latest)


if __name__ == "__main__":
    unittest.main()
