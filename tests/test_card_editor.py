import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import reload_app_modules


class CardEditorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "editor_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()
        product, _changed = await self.db.save_product(
            "https://www.ozon.ru/product/editor",
            {"name": "Исходный товар", "price": 1000, "availability": "in_stock", "image_url": "https://img.test/1.jpg"},
        )
        self.product_id = product.id

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

    async def _draft(self, payload=None):
        response = await self.client.post(
            f"/api/products/{self.product_id}/drafts",
            json={"payload": payload or {}, "comment": "Черновик"},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    async def test_create_update_discard_draft(self):
        draft = await self._draft({"title": "Новый товар"})

        response = await self.client.patch(
            f"/api/products/{self.product_id}/drafts/{draft['draft_id']}",
            json={"revision": draft["revision"], "payload": {"brand": "Brand"}},
        )
        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["payload"]["brand"], "Brand")

        response = await self.client.delete(f"/api/products/{self.product_id}/drafts/{draft['draft_id']}")
        self.assertEqual(response.status_code, 204)

        response = await self.client.get(f"/api/products/{self.product_id}/drafts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["status"], "discarded")

    async def test_validation_errors(self):
        draft = await self._draft({"title": ""})

        response = await self.client.post(f"/api/products/{self.product_id}/drafts/{draft['draft_id']}/validate")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["is_valid"])
        self.assertEqual(data["issues"][0]["field"], "title")

    async def test_apply_creates_persisted_version_event_and_updates_product(self):
        draft = await self._draft({"title": "Ручное название", "price": 1200})

        response = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{draft['draft_id']}/apply",
            json={"revision": draft["revision"], "comment": "Применяю вручную"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["version"]["version_number"], 1)
        self.assertEqual(data["version"]["snapshot"]["title"], "Ручное название")
        self.assertFalse(data["version"]["is_derived"])
        self.assertEqual(data["event"]["event_type"], "product.manual_change_applied")
        self.assertTrue(data["diff"])

        detail = await self.client.get(f"/api/products/{self.product_id}")
        self.assertEqual(detail.json()["name"], "Ручное название")
        self.assertEqual(detail.json()["current_price"], 1200)

    async def test_duplicate_snapshot_is_rejected_without_new_version(self):
        draft = await self._draft({"title": "Ручное название"})
        first = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{draft['draft_id']}/apply",
            json={"revision": draft["revision"]},
        )
        self.assertEqual(first.status_code, 200)

        duplicate = await self._draft({"title": "Ручное название"})
        second = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{duplicate['draft_id']}/apply",
            json={"revision": duplicate["revision"]},
        )

        self.assertEqual(second.status_code, 422)

    async def test_optimistic_locking_returns_409(self):
        stale = await self._draft({"title": "Старый черновик"})
        fresh = await self._draft({"title": "Новая версия"})
        applied = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{fresh['draft_id']}/apply",
            json={"revision": fresh["revision"]},
        )
        self.assertEqual(applied.status_code, 200)

        response = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{stale['draft_id']}/apply",
            json={"revision": stale["revision"]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("conflict", response.json()["detail"])

    async def test_transaction_rolls_back_when_event_write_fails(self):
        draft = await self._draft({"title": "Не должно сохраниться"})

        async def fail_append(*args, **kwargs):
            raise ValueError("boom")

        with patch("app.editor.service.DomainEventRepository.append", fail_append), self.assertRaises(ValueError):
            from app.editor.service import ProductCardEditorService

            await ProductCardEditorService(self.db).apply_draft(
                self.product_id,
                draft["draft_id"],
                revision=draft["revision"],
            )

        response = await self.client.get(f"/api/products/{self.product_id}/versions")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(item["is_derived"] for item in response.json()["items"]))

    async def test_rollback_creates_new_version(self):
        first = await self._draft({"title": "Версия один"})
        first_apply = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{first['draft_id']}/apply",
            json={"revision": first["revision"]},
        )
        self.assertEqual(first_apply.status_code, 200)

        second = await self._draft({"title": "Версия два"})
        second_apply = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{second['draft_id']}/apply",
            json={"revision": second["revision"]},
        )
        self.assertEqual(second_apply.status_code, 200)
        current_version_id = second_apply.json()["version"]["version_id"]

        rollback = await self.client.post(
            f"/api/products/{self.product_id}/versions/1/rollback",
            json={"current_version_id": current_version_id, "reason": "Вернуть первую версию"},
        )

        self.assertEqual(rollback.status_code, 200)
        self.assertEqual(rollback.json()["version"]["version_number"], 3)
        self.assertEqual(rollback.json()["version"]["snapshot"]["title"], "Версия один")
        self.assertEqual(rollback.json()["event"]["event_type"], "product.version_rolled_back")

    async def test_timeline_and_audit_include_manual_event(self):
        draft = await self._draft({"title": "История вручную"})
        response = await self.client.post(
            f"/api/products/{self.product_id}/drafts/{draft['draft_id']}/apply",
            json={"revision": draft["revision"], "comment": "Для истории"},
        )
        self.assertEqual(response.status_code, 200)

        timeline = await self.client.get(f"/api/products/{self.product_id}/timeline?event_type=manual")
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["event_type"], "manual_field_changed")

        audit = await self.client.get(f"/api/products/{self.product_id}/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json()["items"][0]["event_type"], "product.manual_change_applied")

    async def test_domain_event_rejects_secret_payload(self):
        from datetime import UTC, datetime

        from app.domain.events.models import DomainEvent
        from app.domain.events.repository import DomainEventRepository

        async with self.db.session() as session:
            with self.assertRaises(ValueError):
                await DomainEventRepository(session).append(
                    DomainEvent(
                        event_id="product:secret",
                        aggregate_type="product",
                        aggregate_id=str(self.product_id),
                        event_type="product.manual_change_applied",
                        source="user",
                        occurred_at=datetime.now(UTC),
                        payload={"token": "secret"},
                    )
                )

    async def test_create_draft_via_api_with_string_image_urls_splits_into_real_urls(self):
        """D30: a direct API call (no Pydantic schema guards `payload`) that
        sends image_urls as a comma-separated string must not have it
        exploded into one-character 'URLs' by normalize_card_payload()."""
        draft = await self._draft(
            {"image_urls": "https://img.test/a.jpg,https://img.test/b.jpg"}
        )

        self.assertEqual(
            draft["payload"]["image_urls"],
            ["https://img.test/a.jpg", "https://img.test/b.jpg"],
        )

    async def test_create_draft_via_api_with_single_string_image_url(self):
        draft = await self._draft({"image_urls": "https://img.test/a.jpg"})

        self.assertEqual(draft["payload"]["image_urls"], ["https://img.test/a.jpg"])

    async def test_update_draft_via_api_with_string_image_urls_splits_into_real_urls(self):
        draft = await self._draft({"title": "Товар"})

        response = await self.client.patch(
            f"/api/products/{self.product_id}/drafts/{draft['draft_id']}",
            json={
                "revision": draft["revision"],
                "payload": {"image_urls": "https://img.test/a.jpg,https://img.test/b.jpg"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["payload"]["image_urls"],
            ["https://img.test/a.jpg", "https://img.test/b.jpg"],
        )
