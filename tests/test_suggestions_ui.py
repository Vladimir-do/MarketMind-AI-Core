from __future__ import annotations

import os
import unittest

from httpx import ASGITransport, AsyncClient

from tests.helpers import reload_app_modules


class SuggestionsUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Use in-memory SQLite for tests
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.database import Database
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AISuggestion, AIRecommendationResult

        self.db = Database()
        await self.db.init()
        self.queue = DatabaseApprovalQueue(self.db)

        result = AIRecommendationResult(
            product_id="12345",
            suggestions=[
                AISuggestion(
                    field="title",
                    suggestion_type="improve",
                    before="Старый заголовок",
                    after="Новый улучшенный заголовок",
                    reason="SEO оптимизация",
                    confidence=0.85,
                    metadata={"product_name": "Тестовый товар"},
                ),
                AISuggestion(
                    field="description",
                    suggestion_type="expand",
                    before="Краткое описание",
                    after="Развёрнутое описание с ключевыми словами",
                    reason="Увеличение конверсии",
                    confidence=0.72,
                    metadata={"product_name": "Тестовый товар"},
                ),
            ],
        )
        await self.queue.add(result)

        from app.web.app import create_app

        self.app = create_app()
        self.app.state.ai_queue = self.queue
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()

    async def test_suggestions_page(self):
        resp = await self.client.get("/suggestions")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Предложения AI", resp.text)
        self.assertIn("Тестовый товар", resp.text)
        self.assertIn("Новый улучшенный заголовок", resp.text)
        self.assertIn("Ожидают", resp.text)

    async def test_suggestion_detail_page(self):
        resp = await self.client.get("/api/suggestions")
        aid = resp.json()[0]["approval_id"]

        resp = await self.client.get(f"/suggestions/{aid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Было", resp.text)
        self.assertIn("Новое", resp.text)
        self.assertIn("SEO оптимизация", resp.text)

    async def test_suggestion_detail_api(self):
        resp = await self.client.get("/api/suggestions")
        aid = resp.json()[0]["approval_id"]

        resp = await self.client.get(f"/api/suggestions/{aid}")
        self.assertEqual(resp.status_code, 200)
        item = resp.json()
        self.assertEqual(item["approval_id"], aid)
        self.assertEqual(item["product_name"], "Тестовый товар")

    async def test_suggestions_api_empty(self):
        from app.database import Database
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.web.app import create_app

        db = Database()
        await db.init()
        empty_queue = DatabaseApprovalQueue(db)
        app = create_app()
        app.state.ai_queue = empty_queue
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as c:
            resp = await c.get("/api/suggestions")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), [])

            resp = await c.get("/suggestions")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Нет предложений", resp.text)
        await db._engine.dispose()

    async def test_approve_suggestion(self):
        resp = await self.client.get("/api/suggestions")
        items = resp.json()
        self.assertEqual(len(items), 2)
        aid = items[0]["approval_id"]

        resp = await self.client.post(f"/suggestions/{aid}/approve")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Одобрено", resp.text)

    async def test_reject_suggestion(self):
        resp = await self.client.get("/api/suggestions")
        items = resp.json()
        aid = items[1]["approval_id"]

        resp = await self.client.post(
            f"/suggestions/{aid}/reject",
            json={"reason": "Не подходит"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Отклонено", resp.text)

    async def test_filter_by_status(self):
        resp = await self.client.get("/api/suggestions?status=pending")
        items = resp.json()
        self.assertTrue(all(i["status"] == "pending" for i in items))

        resp = await self.client.get("/api/suggestions?status=approved")
        items = resp.json()
        self.assertTrue(all(i["status"] == "approved" for i in items))

    async def test_wrong_id_returns_404(self):
        resp = await self.client.get("/api/suggestions/missing-id")
        self.assertEqual(resp.status_code, 404)

        resp = await self.client.get("/suggestions/missing-id")
        self.assertEqual(resp.status_code, 404)

        resp = await self.client.post("/suggestions/missing-id/approve")
        self.assertEqual(resp.status_code, 404)

        resp = await self.client.post("/suggestions/missing-id/reject")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
