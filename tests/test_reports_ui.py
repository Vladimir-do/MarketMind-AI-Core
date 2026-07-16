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

        from app.web.app import create_app
        from httpx import ASGITransport, AsyncClient

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

    async def test_base_menu_contains_reports_link(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/reports"', resp.text)
        self.assertIn("Отчёты", resp.text)


if __name__ == "__main__":
    unittest.main()
