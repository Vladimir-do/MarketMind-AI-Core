import os
import tempfile
import unittest
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
        pid = await self._get_product_id("Ozon")
        resp = await self.client.get(f"/api/products/{pid}/history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
