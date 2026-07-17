import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import reload_app_modules


class ClientProjectWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["MARKETMIND_DATA_DIR"] = str(root / "data")
        os.environ["MARKETMIND_WORKSPACE_DIR"] = str(root / "workspace")
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(root / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(root / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{(root / 'p6.db').as_posix()}")
        self.db = database.Database()
        await self.db.init()

        from httpx import ASGITransport, AsyncClient

        from app.web.app import create_app

        self.app = create_app()
        self.app.state.db = self.db
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()
        for key in (
            "MARKETMIND_DATA_DIR",
            "MARKETMIND_WORKSPACE_DIR",
            "SCRAPE_ATTEMPTS_JSONL",
            "BLOCK_PATTERNS_JSONL",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    async def _create_project(self, name: str) -> str:
        response = await self.client.post(
            "/api/projects",
            json={"name": name, "client_name": f"Заказчик {name}", "marketplace": "ozon"},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["project_id"]

    async def _import_csv(self, project_id: str, title: str, price: int = 1000) -> dict:
        csv_text = (
            "название,цена,ссылка,маркетплейс\n"
            f"{title},{price},https://example.test/shared-product,ozon\n"
        )
        response = await self.client.post(
            f"/api/projects/{project_id}/imports",
            files={"file": ("../опасный.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    async def _product_id(self, project_id: str) -> int:
        response = await self.client.get(f"/api/projects/{project_id}/products")
        self.assertEqual(response.status_code, 200)
        return response.json()["items"][0]["product_id"]

    async def test_project_crud_and_archive(self):
        project_id = await self._create_project("P6")

        listed = await self.client.get("/api/projects")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["items"]), 1)

        updated = await self.client.patch(
            f"/api/projects/{project_id}",
            json={"status": "ready_for_review", "notes": "Проверить экспорт"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["status"], "ready_for_review")

        archived = await self.client.post(f"/api/projects/{project_id}/archive")
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["status"], "archived")

        visible = await self.client.get("/api/projects")
        self.assertEqual(visible.json()["items"], [])

    async def test_import_stores_source_file_and_project_products(self):
        project_id = await self._create_project("Import")
        result = await self._import_csv(project_id, "Проектный товар")

        self.assertEqual(result["total_products"], 1)
        self.assertEqual(result["file"]["original_filename"], "опасный.csv")
        self.assertNotIn("..", result["file"]["relative_path"])
        self.assertEqual(len(result["file"]["sha256"]), 64)

        products = await self.client.get(f"/api/projects/{project_id}/products")
        self.assertEqual(products.status_code, 200)
        self.assertEqual(products.json()["items"][0]["effective_snapshot"]["title"], "Проектный товар")

    async def test_products_from_different_projects_do_not_mix(self):
        project_a = await self._create_project("A")
        project_b = await self._create_project("B")
        await self._import_csv(project_a, "Товар A", price=1000)
        await self._import_csv(project_b, "Товар B", price=2000)

        product_id = await self._product_id(project_a)
        card_a = await self.client.get(f"/api/projects/{project_a}/products/{product_id}/effective-card")
        card_b = await self.client.get(f"/api/projects/{project_b}/products/{product_id}/effective-card")

        self.assertEqual(card_a.status_code, 200)
        self.assertEqual(card_b.status_code, 200)
        self.assertEqual(card_a.json()["effective_snapshot"]["title"], "Товар A")
        self.assertEqual(card_b.json()["effective_snapshot"]["title"], "Товар B")

    async def test_project_draft_apply_changes_only_effective_card(self):
        project_a = await self._create_project("A")
        project_b = await self._create_project("B")
        await self._import_csv(project_a, "Исходное A")
        await self._import_csv(project_b, "Исходное B")
        product_id = await self._product_id(project_a)

        draft = await self.client.post(
            f"/api/projects/{project_a}/products/{product_id}/drafts",
            json={"payload": {"title": "Ручное название A"}},
        )
        self.assertEqual(draft.status_code, 200)
        applied = await self.client.post(
            f"/api/projects/{project_a}/products/{product_id}/drafts/{draft.json()['draft_id']}/apply",
            json={"revision": draft.json()["revision"], "comment": "Для заказчика A"},
        )
        self.assertEqual(applied.status_code, 200)

        card_a = (await self.client.get(f"/api/projects/{project_a}/products/{product_id}/effective-card")).json()
        card_b = (await self.client.get(f"/api/projects/{project_b}/products/{product_id}/effective-card")).json()
        legacy = (await self.client.get(f"/api/products/{product_id}")).json()

        self.assertEqual(card_a["effective_snapshot"]["title"], "Ручное название A")
        self.assertEqual(card_b["effective_snapshot"]["title"], "Исходное B")
        self.assertNotEqual(legacy["name"], "Ручное название A")

    async def test_export_uses_effective_card_and_sanitizes_formula_values(self):
        project_id = await self._create_project("Export")
        await self._import_csv(project_id, "=Опасная формула")

        preview = await self.client.get(f"/api/projects/{project_id}/export-preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["total_products"], 1)
        self.assertEqual(preview.json()["items"][0]["title"], "'=Опасная формула")

        export = await self.client.post(
            f"/api/projects/{project_id}/exports",
            json={"file_format": "csv", "marketplace_profile": "universal"},
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("exports/", export.json()["relative_path"])

    async def test_project_report_contains_only_project_data(self):
        project_a = await self._create_project("Report A")
        project_b = await self._create_project("Report B")
        await self._import_csv(project_a, "Отчёт A")
        await self._import_csv(project_b, "Отчёт B")

        report = await self.client.get(f"/api/projects/{project_a}/report-preview")
        self.assertEqual(report.status_code, 200)
        data = report.json()
        self.assertEqual(data["project_id"], project_a)
        self.assertEqual(data["total_products"], 1)

        created = await self.client.post(f"/api/projects/{project_a}/reports", json={"file_format": "html"})
        self.assertEqual(created.status_code, 200)
        self.assertIn("reports/", created.json()["relative_path"])

    async def test_unsupported_import_format_returns_422(self):
        project_id = await self._create_project("Bad file")
        response = await self.client.post(
            f"/api/projects/{project_id}/imports",
            files={"file": ("bad.exe", b"not a table", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
