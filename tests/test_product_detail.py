import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.helpers import reload_app_modules


class ProductDetailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "detail_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

        await self.db.save_product(
            "https://www.ozon.ru/product/123",
            {"name": "Тестовый товар Ozon", "price": 1500, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.ozon.ru/product/123",
            {"name": "Тестовый товар Ozon", "price": 1750, "availability": "out_of_stock"},
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/456",
            {"name": "Другой товар WB", "price": 2000, "availability": "in_stock"},
        )

        from app.web.app import create_app
        from httpx import AsyncClient, ASGITransport

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

    async def _get_product_id(self, name_fragment: str) -> int:
        products = await self.db.get_all_products()
        for p in products:
            if name_fragment in (p.name or ""):
                return p.id
        raise RuntimeError(f"Product with '{name_fragment}' not found")

    async def test_product_detail_page(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Тестовый товар Ozon", resp.text)
        self.assertIn("Карточка товара", resp.text)

    async def test_product_detail_api(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], pid)
        self.assertEqual(data["name"], "Тестовый товар Ozon")
        self.assertIn("marketplace", data)
        self.assertIn("current_price", data)
        self.assertIn("availability", data)
        self.assertIn("first_seen", data)
        self.assertIn("last_check", data)

    async def test_product_detail_404(self):
        resp = await self.client.get("/products/99999")
        self.assertEqual(resp.status_code, 404)
        resp2 = await self.client.get("/api/products/99999")
        self.assertEqual(resp2.status_code, 404)

    async def test_product_detail_prices(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/prices")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("price", data[0])
        self.assertIn("availability_status", data[0])
        self.assertIn("recorded_at", data[0])

    async def test_product_detail_analysis(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/analysis")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("score", data)
        self.assertIn("tier", data)
        self.assertIn("findings", data)
        self.assertIn("recommendations", data)
        self.assertIsInstance(data["findings"], list)
        self.assertIsInstance(data["recommendations"], list)

    async def test_product_detail_suggestions(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/suggestions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    async def test_product_detail_history(self):
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AISuggestion, AIRecommendationResult

        pid = await self._get_product_id("Ozon")
        queue = DatabaseApprovalQueue(self.db)
        await queue.add(
            AIRecommendationResult(
                product_id=str(pid),
                suggestions=[
                    AISuggestion(
                        field="name",
                        suggestion_type="rewrite",
                        before="Старое название",
                        after="Новое название",
                        reason="Название понятнее",
                        confidence=0.9,
                    )
                ],
            )
        )
        resp = await self.client.get(f"/api/products/{pid}/history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        expected_keys = {
            "approval_id",
            "field",
            "suggestion_type",
            "before_value",
            "after_value",
            "reason",
            "confidence",
            "status",
            "reject_reason",
            "created_at",
            "reviewed_at",
            "applied_at",
        }
        self.assertEqual(set(data[0].keys()), expected_keys)
        self.assertNotIn("event_type", data[0])

    async def test_product_detail_timeline(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["product_id"], pid)
        self.assertIn("items", data)
        self.assertIn("pagination", data)
        event_types = {item["event_type"] for item in data["items"]}
        self.assertIn("product_imported", event_types)
        self.assertIn("price_changed", event_types)
        self.assertIn("stock_changed", event_types)

    async def test_product_detail_history_sorted_by_time(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline")
        self.assertEqual(resp.status_code, 200)
        dates = [item["occurred_at"] for item in resp.json()["items"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    async def test_product_detail_history_price_old_new_values(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline?event_type=price")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["items"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_group"], "price")
        self.assertEqual(data[0]["old_value"], "1500 ₽")
        self.assertEqual(data[0]["new_value"], "1750 ₽")

    async def test_product_detail_history_stock_filter(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline?event_type=stock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["items"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_group"], "stock")
        self.assertEqual(data[0]["old_value"], "in_stock")
        self.assertEqual(data[0]["new_value"], "out_of_stock")

    async def test_product_detail_history_manual_filter_empty(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline?event_type=manual")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"], [])

    async def test_product_detail_history_ai_approve_reject_and_rollback(self):
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AISuggestion, AIRecommendationResult

        pid = await self._get_product_id("Ozon")
        queue = DatabaseApprovalQueue(self.db)

        approved = await queue.add(
            AIRecommendationResult(
                product_id=str(pid),
                suggestions=[
                    AISuggestion(
                        field="name",
                        suggestion_type="rewrite",
                        before="Старое название",
                        after="Новое название",
                        reason="Название понятнее для покупателя",
                        confidence=0.91,
                    )
                ],
            )
        )
        rejected = await queue.add(
            AIRecommendationResult(
                product_id=str(pid),
                suggestions=[
                    AISuggestion(
                        field="description",
                        suggestion_type="rewrite",
                        before="Старое описание",
                        after="Новое описание",
                        reason="Описание подробнее",
                        confidence=0.72,
                    )
                ],
            )
        )
        rollback = await queue.add(
            AIRecommendationResult(
                product_id=str(pid),
                suggestions=[
                    AISuggestion(
                        field="name",
                        suggestion_type="rewrite",
                        before="До отката",
                        after="После отката",
                        reason="Проверка отката",
                        confidence=0.8,
                    )
                ],
            )
        )

        await queue.approve(approved[0].approval_id)
        await queue.reject(rejected[0].approval_id, reason="Не подходит")
        await queue.approve(rollback[0].approval_id)

        from app.database import ApprovalRecord
        from sqlalchemy import select

        async with self.db.session() as s:
            record = (
                await s.execute(
                    select(ApprovalRecord).where(
                        ApprovalRecord.approval_id == rollback[0].approval_id
                    )
                )
            ).scalar_one()
            record.snapshot_before = (
                '{"field": "name", "value": "До отката", '
                f'"timestamp": "{datetime.now(timezone.utc).isoformat()}"}}'
            )
            record.applied_at = datetime.now(timezone.utc)
            await s.commit()
        await queue.rollback(rollback[0].approval_id)

        resp = await self.client.get(f"/api/products/{pid}/timeline")
        self.assertEqual(resp.status_code, 200)
        event_types = {item["event_type"] for item in resp.json()["items"]}
        self.assertIn("ai_suggestion_created", event_types)
        self.assertIn("ai_suggestion_approved", event_types)
        self.assertIn("ai_suggestion_rejected", event_types)
        self.assertIn("ai_suggestion_applied", event_types)
        self.assertIn("ai_suggestion_rolled_back", event_types)

    async def test_product_detail_history_has_no_duplicate_event_ids(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline")
        self.assertEqual(resp.status_code, 200)
        event_ids = [item["event_id"] for item in resp.json()["items"]]
        self.assertEqual(len(event_ids), len(set(event_ids)))

    async def test_product_detail_timeline_pagination(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/timeline?limit=1&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pagination"]["limit"], 1)
        self.assertEqual(data["pagination"]["offset"], 0)
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_offset"], 1)

    async def test_product_detail_history_partial(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}/history?event_type=price")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Все события", resp.text)
        self.assertIn("Изменение цены", resp.text)

    async def test_product_detail_history_404(self):
        resp = await self.client.get("/api/products/99999/history")
        self.assertEqual(resp.status_code, 404)
        timeline_resp = await self.client.get("/api/products/99999/timeline")
        self.assertEqual(timeline_resp.status_code, 404)
        html_resp = await self.client.get("/products/99999/history")
        self.assertEqual(html_resp.status_code, 404)
