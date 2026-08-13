import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

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
        self.assertIn("SEO-аудит карточки", resp.text)
        self.assertIn("В очередь", resp.text)

    async def test_product_detail_page_hides_placeholder_image_url(self):
        product, _changed = await self.db.save_product(
            "file://import/demo-image",
            {
                "name": "Товар с учебным фото",
                "price": 1000,
                "availability": "in_stock",
                "image_url": "https://example.com/img/demo.jpg",
            },
        )

        resp = await self.client.get(f"/products/{product.id}")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("data:image/svg+xml;base64,", resp.text)
        self.assertNotIn('src="https://example.com/img/demo.jpg"', resp.text)

    async def test_generate_ai_suggestions_queues_job(self):
        pid = await self._get_product_id("Ozon")

        resp = await self.client.post(f"/api/products/{pid}/ai-suggestions")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("поставлена в очередь", resp.text)
        self.assertIn("Job:", resp.text)

        jobs = await self.db.get_recent_jobs(job_type="ai_product_suggestions")
        self.assertTrue(jobs)
        self.assertEqual(jobs[0].job_type, "ai_product_suggestions")
        self.assertIn('"product_id": %s' % pid, jobs[0].payload_json)

    async def test_ai_suggestion_job_writes_pending_approval(self):
        from app.ai_recommendation.job_queue import process_product_ai_suggestion_job
        from app.ai_recommendation.provider import AIResponse

        class FakeProvider:
            def is_available(self):
                return True

            def name(self):
                return "fake"

            async def complete(self, prompt, system="", max_tokens=2048, temperature=0.3):
                return AIResponse(
                    text=(
                        '[{"field":"description","suggestion_type":"expand",'
                        '"before":"","after":"Подробное описание товара",'
                        '"reason":"Описание повышает качество карточки",'
                        '"confidence":0.9,"source_finding":"description"}]'
                    ),
                    model="fake-model",
                )

        pid = await self._get_product_id("Ozon")
        job = await self.db.create_job("ai_product_suggestions", {"product_id": pid})
        with patch("app.ai_recommendation.job_queue.create_configured_provider", return_value=FakeProvider()):
            result = await process_product_ai_suggestion_job(self.app, job.job_id, pid)

        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["approval_ids"]), 1)

        suggestions = await self.client.get("/api/ai-suggestions?status=pending")
        self.assertEqual(suggestions.status_code, 200)
        self.assertEqual(len(suggestions.json()), 1)

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

    async def test_страница_товара_содержит_seo_блок(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SEO-аудит карточки", resp.text)

    async def test_seo_api_возвращает_полную_структуру(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/seo")
        self.assertEqual(resp.status_code, 200)
        данные = resp.json()

        self.assertIsInstance(данные["score"], int)
        self.assertGreaterEqual(данные["score"], 0)
        self.assertLessEqual(данные["score"], 100)
        self.assertIn(данные["tier"], {"strong", "usable", "needs_work", "weak"})
        self.assertIsInstance(данные["ready"], bool)
        self.assertIsInstance(данные["findings"], list)
        self.assertIsInstance(данные["recommendations"], list)

        for находка in данные["findings"]:
            self.assertIn("rule", находка)
            self.assertIn("field", находка)
            self.assertIn("severity", находка)
            self.assertIn("message", находка)
            self.assertIn(находка["severity"], {"critical", "warning", "info"})

        for rec in данные["recommendations"]:
            self.assertIn("field", rec)
            self.assertIn("action", rec)
            self.assertIn("priority", rec)
            self.assertIn("reason", rec)
            self.assertIn(rec["priority"], {1, 2, 3})

    async def test_seo_api_404_для_несуществующего_товара(self):
        resp = await self.client.get("/api/products/99999/seo")
        self.assertEqual(resp.status_code, 404)

    async def test_seo_страница_показывает_блок_аудита(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SEO-аудит карточки", resp.text)

    async def test_seo_балл_отображается_на_странице(self):
        pid = await self._get_product_id("Ozon")
        seo_resp = await self.client.get(f"/api/products/{pid}/seo")
        балл = seo_resp.json()["score"]

        страница = await self.client.get(f"/products/{pid}")
        self.assertEqual(страница.status_code, 200)
        self.assertIn(str(балл), страница.text)

    async def test_seo_метка_уровня_на_странице(self):
        pid = await self._get_product_id("Ozon")
        seo_resp = await self.client.get(f"/api/products/{pid}/seo")
        уровень = seo_resp.json()["tier"]

        метки = {
            "strong": "Сильная карточка",
            "usable": "Можно использовать",
            "needs_work": "Нужна доработка",
            "weak": "Слабая SEO-база",
        }
        ожидаемая_метка = метки.get(уровень, "")
        страница = await self.client.get(f"/products/{pid}")
        self.assertEqual(страница.status_code, 200)
        if ожидаемая_метка:
            self.assertIn(ожидаемая_метка, страница.text)

    async def test_seo_рекомендации_на_странице(self):
        pid = await self._get_product_id("Ozon")
        seo_resp = await self.client.get(f"/api/products/{pid}/seo")
        рекомендации = seo_resp.json()["recommendations"]

        страница = await self.client.get(f"/products/{pid}")
        self.assertEqual(страница.status_code, 200)
        if рекомендации:
            self.assertIn(рекомендации[0]["action"], страница.text)
        else:
            self.assertIn("Критичных SEO-рекомендаций нет", страница.text)

    async def test_seo_разные_товары_имеют_разные_баллы(self):
        pid1 = await self._get_product_id("Ozon")
        pid2 = await self._get_product_id("WB")
        seo1 = (await self.client.get(f"/api/products/{pid1}/seo")).json()
        seo2 = (await self.client.get(f"/api/products/{pid2}/seo")).json()
        self.assertIsInstance(seo1["score"], int)
        self.assertIsInstance(seo2["score"], int)
        self.assertNotEqual(pid1, pid2)

    async def test_product_semantic_core_endpoint_возвращает_данные(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/semantic-core")
        self.assertEqual(resp.status_code, 200)
        данные = resp.json()
        self.assertEqual(данные["product_id"], pid)
        self.assertIn("primary_terms", данные)
        self.assertIn("coverage_score", данные)
        self.assertIsInstance(данные["coverage_score"], float)

    async def test_product_semantic_core_404(self):
        resp = await self.client.get("/api/products/99999/semantic-core")
        self.assertEqual(resp.status_code, 404)

    async def test_product_detail_suggestions(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/suggestions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    async def test_product_detail_history(self):
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion

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
        from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion

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

        from sqlalchemy import select

        from app.database import ApprovalRecord

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
                f'"timestamp": "{datetime.now(UTC).isoformat()}"}}'
            )
            record.applied_at = datetime.now(UTC)
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

    async def test_product_detail_timeline_large_offset(self):
        from app.database import ApprovalRecord

        pid = await self._get_product_id("Ozon")
        async with self.db.session() as s:
            for index in range(1105):
                s.add(
                    ApprovalRecord(
                        approval_id=f"bulk{index}",
                        product_id=str(pid),
                        field="name",
                        suggestion_type="rewrite",
                        before_value="A",
                        after_value=f"B{index}",
                        reason="bulk",
                        confidence=0.5,
                        status="pending",
                        created_at=datetime(2026, 7, 17, 0, 0, tzinfo=UTC),
                    )
                )
            await s.commit()

        resp = await self.client.get(f"/api/products/{pid}/timeline?limit=1&offset=1000")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pagination"]["offset"], 1000)
        self.assertTrue(data["pagination"]["has_more"])

    async def test_product_detail_timeline_filters_approval_by_lifecycle_date(self):
        from app.database import ApprovalRecord

        pid = await self._get_product_id("Ozon")
        async with self.db.session() as s:
            s.add(
                ApprovalRecord(
                    approval_id="lifecycle-date",
                    product_id=str(pid),
                    field="name",
                    suggestion_type="rewrite",
                    before_value="A",
                    after_value="B",
                    reason="created before range",
                    confidence=0.8,
                    status="approved",
                    created_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
                    reviewed_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
                )
            )
            await s.commit()

        resp = await self.client.get(
            f"/api/products/{pid}/timeline"
            "?date_from=2026-07-17T00:00:00+00:00"
            "&date_to=2026-07-17T23:59:59+00:00"
        )
        self.assertEqual(resp.status_code, 200)
        event_types = {item["event_type"] for item in resp.json()["items"]}
        self.assertIn("ai_suggestion_approved", event_types)
        self.assertNotIn("ai_suggestion_created", event_types)

    async def test_product_detail_timeline_price_predecessor_for_date_from(self):
        from sqlalchemy import select

        from app.database import PriceHistory

        pid = await self._get_product_id("Ozon")
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(PriceHistory)
                    .where(PriceHistory.product_id == pid)
                    .order_by(PriceHistory.id)
                )
            ).scalars().all()
            rows[0].recorded_at = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
            rows[1].recorded_at = datetime(2026, 7, 17, 11, 0, tzinfo=UTC)
            await s.commit()

        resp = await self.client.get(
            f"/api/products/{pid}/timeline?event_type=price&date_from=2026-07-17T10:30:00+00:00"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["items"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["old_value"], "1500 ₽")
        self.assertEqual(data[0]["new_value"], "1750 ₽")

    async def test_product_detail_history_partial(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}/history?event_type=price")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Все события", resp.text)
        self.assertIn("Изменение цены", resp.text)

    async def test_product_detail_history_partial_updates_active_filter(self):
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/products/{pid}/history?event_type=manual")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('hx-get="/products/', resp.text)
        self.assertIn("Истории по выбранному фильтру пока нет.", resp.text)
        self.assertIn("bg-blue-600 text-white border-blue-600", resp.text)

    async def test_product_detail_history_404(self):
        resp = await self.client.get("/api/products/99999/history")
        self.assertEqual(resp.status_code, 404)
        timeline_resp = await self.client.get("/api/products/99999/timeline")
        self.assertEqual(timeline_resp.status_code, 404)
        html_resp = await self.client.get("/products/99999/history")
        self.assertEqual(html_resp.status_code, 404)
