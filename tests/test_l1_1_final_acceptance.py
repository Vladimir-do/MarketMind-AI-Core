import csv
import io
import os
import tempfile
import unittest
from pathlib import Path

import openpyxl

from tests.helpers import reload_app_modules


class L11FinalAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["MARKETMIND_DATA_DIR"] = str(root / "data")
        os.environ["MARKETMIND_WORKSPACE_DIR"] = str(root / "workspace")
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(root / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(root / "block_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{(root / 'l1_1.db').as_posix()}")
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
            "DATABASE_URL",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    async def _create_project(self, name: str = "L1.1") -> str:
        response = await self.client.post(
            "/api/projects",
            json={"name": name, "client_name": "Тестовый заказчик", "marketplace": "ozon"},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["project_id"]

    async def _import_basic_csv(self, project_id: str) -> int:
        response = await self.client.post(
            f"/api/projects/{project_id}/imports",
            files={"file": ("basic.csv", "Название,Цена,Ссылка\nТовар,100,https://example.test/p\n".encode(), "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        products = await self.client.get(f"/api/projects/{project_id}/products")
        self.assertEqual(products.status_code, 200)
        return products.json()["items"][0]["product_id"]

    async def test_windows_1251_requires_confirmation_and_imports_after_approval(self):
        project_id = await self._create_project("CP1251")
        csv_text = "Название;Цена;Ссылка\nРусский товар;250;https://example.test/cp\n"
        preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("cp1251.csv", csv_text.encode("cp1251"), "text/csv")},
        )
        self.assertEqual(preview.status_code, 200)
        data = preview.json()
        self.assertEqual(data["preview"]["encoding"], "windows-1251")
        self.assertTrue(data["preview"]["requires_confirmation"])
        self.assertTrue(any("Windows-1251" in item for item in data["preview"]["warnings"]))

        blocked = await self.client.post(
            f"/api/projects/{project_id}/imports",
            json={"stored_file": data["stored_file"], "mapping": data["preview"]["suggested_mapping"]},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.json()["status"], "warning_confirmation_required")

        imported = await self.client.post(
            f"/api/projects/{project_id}/imports",
            json={
                "stored_file": data["stored_file"],
                "mapping": data["preview"]["suggested_mapping"],
                "confirm_warnings": True,
            },
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["file"]["encoding"], "windows-1251")
        self.assertEqual(imported.json()["total_products"], 1)

    async def test_utf8_bom_ascii_and_corrupt_csv_encoding_paths(self):
        project_id = await self._create_project("Encoding")
        utf8_bom = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("bom.csv", "\ufeffНазвание,Цена\nТовар,1\n".encode("utf-8"), "text/csv")},
        )
        self.assertEqual(utf8_bom.status_code, 200)
        self.assertEqual(utf8_bom.json()["preview"]["encoding"], "utf-8-sig")

        ascii_file = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("ascii.csv", b"Title,Price\nProduct,1\n", "text/csv")},
        )
        self.assertEqual(ascii_file.status_code, 200)
        self.assertEqual(ascii_file.json()["preview"]["encoding"], "utf-8")

        corrupt = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("bad.csv", b"\x81\x81\x81\x81", "text/csv")},
        )
        self.assertEqual(corrupt.status_code, 422)

    async def test_mapping_presets_can_be_saved_suggested_and_deleted(self):
        project_id = await self._create_project("Preset")
        csv_text = "Название;Цена;Поставщик\nТовар;100;ООО Ромашка\n"
        preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("preset.csv", csv_text.encode(), "text/csv")},
        )
        self.assertEqual(preview.status_code, 200)
        data = preview.json()
        imported = await self.client.post(
            f"/api/projects/{project_id}/imports",
            json={
                "stored_file": data["stored_file"],
                "mapping": data["preview"]["suggested_mapping"],
                "save_preset": True,
                "preset_name": "Поставщик Ромашка",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(imported.status_code, 200)

        second_preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("preset2.csv", csv_text.encode(), "text/csv")},
        )
        self.assertEqual(second_preview.status_code, 200)
        preset = second_preview.json()["suggested_preset"]
        self.assertIsNotNone(preset)
        self.assertEqual(preset["name"], "Поставщик Ромашка")

        deleted = await self.client.delete(f"/api/projects/{project_id}/import-presets/{preset['preset_id']}")
        self.assertEqual(deleted.status_code, 200)
        after_delete = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("preset3.csv", csv_text.encode(), "text/csv")},
        )
        self.assertIsNone(after_delete.json()["suggested_preset"])

    async def test_import_error_report_csv_is_downloadable_and_sanitized(self):
        project_id = await self._create_project("Errors")
        csv_text = "Название,Цена,Колонка\n,=1+1,@SUM(A1:A2)\n"
        preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("errors.csv", csv_text.encode(), "text/csv")},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertGreaterEqual(preview.json()["counts"]["errors"], 1)

        report = await self.client.post(
            f"/api/projects/{project_id}/imports/error-report.csv",
            json={"stored_file": preview.json()["stored_file"]},
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn("text/csv", report.headers["content-type"])
        self.assertIn("attachment", report.headers["content-disposition"])
        rows = list(csv.DictReader(io.StringIO(report.text.lstrip("\ufeff"))))
        self.assertTrue(rows)
        self.assertIn("row_number", rows[0])
        self.assertEqual(rows[0]["severity"], "error")

    async def test_download_routes_are_project_scoped_and_return_safe_fileresponse(self):
        project_a = await self._create_project("Downloads A")
        project_b = await self._create_project("Downloads B")
        await self._import_basic_csv(project_a)
        await self._import_basic_csv(project_b)
        export_csv = (await self.client.post(f"/api/projects/{project_a}/exports", json={"file_format": "csv"})).json()
        export_json = (await self.client.post(f"/api/projects/{project_a}/exports", json={"file_format": "json"})).json()
        export_xlsx = (await self.client.post(f"/api/projects/{project_a}/exports", json={"file_format": "xlsx"})).json()
        report_html = (await self.client.post(f"/api/projects/{project_a}/reports", json={"file_format": "html"})).json()
        report_json = (await self.client.post(f"/api/projects/{project_a}/reports", json={"file_format": "json"})).json()
        report_csv = (await self.client.post(f"/api/projects/{project_a}/reports", json={"file_format": "csv"})).json()

        from fastapi import HTTPException

        from app.web.routes.projects import _download_project_artifact

        for artifact in (export_csv, export_json, export_xlsx, report_html, report_json, report_csv):
            response = _download_project_artifact(project_a, artifact["relative_path"])
            self.assertEqual(Path(response.path).name, Path(artifact["relative_path"]).name)
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertNotIn("..", response.headers["content-disposition"])

        with self.assertRaises(HTTPException) as missing:
            _download_project_artifact(project_b, export_csv["relative_path"])
        self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(HTTPException) as traversal:
            _download_project_artifact(project_a, "../secret.csv")
        self.assertEqual(traversal.exception.status_code, 404)

    async def test_project_export_and_report_htmx_return_russian_partials(self):
        project_id = await self._create_project("HTMX")
        await self._import_basic_csv(project_id)

        export = await self.client.post(
            f"/api/projects/{project_id}/exports",
            json={"file_format": "csv"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("Экспорт CSV создан", export.text)
        self.assertIn("/download", export.text)
        self.assertNotIn('"relative_path"', export.text)

        report_page = await self.client.get(f"/projects/{project_id}/reports")
        self.assertEqual(report_page.status_code, 200)
        self.assertIn("Созданные отчёты", report_page.text)

        report = await self.client.post(
            f"/api/projects/{project_id}/reports",
            json={"file_format": "html"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn("Отчёт HTML создан", report.text)
        self.assertIn("/download", report.text)
        self.assertNotIn('"relative_path"', report.text)

    async def test_demo_fixture_full_local_workflow(self):
        project_id = await self._create_project("Demo fixture")
        fixture = Path(__file__).resolve().parent / "fixtures" / "l1_demo_products.csv"
        content = fixture.read_bytes()
        preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={"file": ("l1_demo_products.csv", content, "text/csv")},
        )
        self.assertEqual(preview.status_code, 200)
        data = preview.json()
        self.assertEqual(data["preview"]["row_count"], 20)
        self.assertGreaterEqual(len(data["preview"]["errors"]), 2)

        imported = await self.client.post(
            f"/api/projects/{project_id}/imports",
            json={
                "stored_file": data["stored_file"],
                "mapping": data["preview"]["suggested_mapping"],
                "save_preset": True,
                "preset_name": "Demo L1.1",
            },
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["total_products"], 18)
        self.assertEqual(imported.json()["errors"], 2)

        products = await self.client.get(f"/api/projects/{project_id}/products")
        self.assertEqual(products.status_code, 200)
        product_id = products.json()["items"][0]["product_id"]
        draft = await self.client.post(
            f"/api/projects/{project_id}/products/{product_id}/drafts",
            json={"payload": {"title": "Ручная правка demo"}},
        )
        applied = await self.client.post(
            f"/api/projects/{project_id}/products/{product_id}/drafts/{draft.json()['draft_id']}/apply",
            json={"revision": draft.json()["revision"], "comment": "Приёмка L1.1"},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        rollback = await self.client.post(
            f"/api/projects/{project_id}/products/{product_id}/versions/{applied.json()['version']['version_number']}/rollback",
            json={"current_version_id": applied.json()["version"]["version_id"], "reason": "Проверка rollback"},
        )
        self.assertEqual(rollback.status_code, 200)
        export = await self.client.post(f"/api/projects/{project_id}/exports", json={"file_format": "csv"})
        report = await self.client.post(f"/api/projects/{project_id}/reports", json={"file_format": "html"})
        self.assertEqual(export.status_code, 200)
        self.assertEqual(report.status_code, 200)
        self.assertEqual(export.json()["manifest"]["product_count"], 18)

    async def test_xlsx_copy_of_demo_fixture_can_be_previewed(self):
        project_id = await self._create_project("Demo XLSX")
        fixture = Path(__file__).resolve().parent / "fixtures" / "l1_demo_products.csv"
        rows = list(csv.reader(io.StringIO(fixture.read_text(encoding="utf-8")), delimiter=";"))
        workbook_path = Path(self.tmp.name) / "demo.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Товары"
        for row in rows:
            sheet.append(row)
        workbook.save(workbook_path)
        preview = await self.client.post(
            f"/api/projects/{project_id}/imports/preview",
            files={
                "file": (
                    "demo.xlsx",
                    workbook_path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["preview"]["row_count"], 20)


if __name__ == "__main__":
    unittest.main()
