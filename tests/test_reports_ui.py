import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import reload_app_modules


class ReportsUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "reports_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

        from httpx import ASGITransport, AsyncClient

        from app.web.app import create_app

        self.app = create_app()
        self.app.state.db = self.db
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()
        os.environ.pop("SCRAPE_ATTEMPTS_JSONL", None)
        os.environ.pop("BLOCK_PATTERNS_JSONL", None)
        self.tmp.cleanup()

    async def _seed_catalog(self):
        await self.db.save_product(
            "https://www.ozon.ru/product/100",
            {"name": "Хорошая карточка", "price": 2500, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/200",
            {"name": "", "price": None, "availability": "out_of_stock"},
        )

    async def test_reports_page_empty_db(self):
        resp = await self.client.get("/reports")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Клиентский отчёт", resp.text)
        self.assertIn("Товаров", resp.text)

    async def test_client_summary_api_empty_db(self):
        resp = await self.client.get("/api/reports/client-summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["summary"]["total_products"], 0)
        self.assertIn("recommended_actions", data)
        self.assertEqual(data["suggestions"]["total"], 0)

    async def test_client_summary_api_with_products(self):
        await self._seed_catalog()
        resp = await self.client.get("/api/reports/client-summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["summary"]["total_products"], 2)
        self.assertGreaterEqual(len(data["top_issues"]), 1)
        self.assertIn("attention_products", data)
        self.assertIn("marketplaces", data)

    async def test_reports_page_with_products(self):
        await self._seed_catalog()
        resp = await self.client.get("/reports")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Топ проблем", resp.text)
        self.assertIn("Рекомендуемые действия", resp.text)
        self.assertIn("Товары, требующие внимания", resp.text)

    async def _seed_approval_records(self):
        """Seed ApprovalRecord rows covering every status the DB can hold:
        pending, approved, rejected, rolled_back (see app/database/models.py
        ApprovalRecord.status and app/ai_recommendation/db_approval.py's
        approve()/reject()/rollback())."""
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion

        queue = DatabaseApprovalQueue(self.db)

        def make_result(product_id, **kwargs):
            defaults = dict(
                field="title", suggestion_type="improve", before="Old",
                after="New", reason="Better SEO", confidence=0.9,
            )
            defaults.update(kwargs)
            return AIRecommendationResult(product_id=product_id, suggestions=[AISuggestion(**defaults)])

        pending = (await queue.add(make_result("p1")))[0]
        approved = (await queue.add(make_result("p2")))[0]
        rejected = (await queue.add(make_result("p3")))[0]
        rolled_back = (await queue.add(make_result("p4")))[0]

        await queue.approve(approved.approval_id)
        await queue.reject(rejected.approval_id, reason="test")

        # queue.rollback() requires a populated snapshot_before (set by
        # apply_approved(), not by add()) -- set the status directly here,
        # this is fixture seeding, not a claim about the rollback() flow.
        from sqlalchemy import select

        from app.database import ApprovalRecord

        async with self.db.session() as s:
            record = (await s.execute(
                select(ApprovalRecord).where(ApprovalRecord.approval_id == rolled_back.approval_id)
            )).scalar_one()
            record.status = "rolled_back"
            await s.commit()

        return pending, approved, rejected, rolled_back

    async def test_client_summary_api_suggestion_counts_reflect_approval_record_statuses(self):
        await self._seed_approval_records()

        resp = await self.client.get("/api/reports/client-summary")

        self.assertEqual(resp.status_code, 200)
        suggestions = resp.json()["suggestions"]
        self.assertEqual(suggestions["total"], 4)
        self.assertEqual(suggestions["pending"], 1)
        self.assertEqual(suggestions["approved"], 1)
        self.assertEqual(suggestions["rejected"], 1)
        self.assertEqual(suggestions["rolled_back"], 1)

    async def test_client_summary_api_pending_suggestions_trigger_recommended_action(self):
        await self._seed_approval_records()

        resp = await self.client.get("/api/reports/client-summary")

        self.assertIn(
            "Проверить ожидающие AI-предложения и принять или отклонить каждое вручную.",
            resp.json()["recommended_actions"],
        )

    async def test_base_menu_contains_reports_link(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/reports"', resp.text)
        self.assertIn("Legacy отчёты", resp.text)


if __name__ == "__main__":
    unittest.main()
