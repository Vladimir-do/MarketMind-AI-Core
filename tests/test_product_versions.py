import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import reload_app_modules


class ProductVersionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "versions_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.db = database.Database()
        await self.db.init()

        await self.db.save_product(
            "https://www.ozon.ru/product/versioned",
            {"name": "Версионный товар", "price": 1000, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.ozon.ru/product/versioned",
            {"name": "Версионный товар", "price": 1200, "availability": "out_of_stock"},
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

    async def _product_id(self) -> int:
        products = await self.db.get_all_products()
        for product in products:
            if product.name == "Версионный товар":
                return product.id
        raise RuntimeError("Versioned product not found")

    async def test_versions_api_returns_derived_versions(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/api/products/{product_id}/versions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["product_id"], product_id)
        self.assertIn("items", data)
        self.assertIn("pagination", data)
        version_types = {item["version_type"] for item in data["items"]}
        self.assertIn("import", version_types)
        self.assertIn("price", version_types)
        self.assertIn("stock", version_types)

    async def test_versions_api_pagination(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/api/products/{product_id}/versions?limit=1&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["pagination"]["limit"], 1)
        self.assertTrue(data["pagination"]["has_more"])

    async def test_version_detail_api(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/api/products/{product_id}/versions/2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["product_id"], product_id)
        self.assertEqual(data["version_number"], 2)
        self.assertIn("snapshot", data)
        self.assertIn("changes", data)
        self.assertTrue(data["is_derived"])
        self.assertEqual(data["snapshot_completeness"], "partial")
        self.assertIn("known_fields", data)
        self.assertIn("unknown_fields", data)
        self.assertIn("source_event_ids", data)
        self.assertFalse(data["quality_score_is_historical"])

    async def test_version_compare_api(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/api/products/{product_id}/compare?from=1&to=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["product_id"], product_id)
        self.assertEqual(data["from_version"], 1)
        self.assertEqual(data["to_version"], 2)
        fields = {item["field"] for item in data["changes"]}
        self.assertIn("price", fields)
        self.assertIn("warnings", data)

    async def test_versions_page(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/products/{product_id}/versions")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Версии карточки товара", resp.text)
        self.assertIn("Сравнить", resp.text)
        self.assertIn("Частично восстановленная версия", resp.text)

    async def test_compare_page(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/products/{product_id}/compare?from=1&to=2")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Сравнение версий", resp.text)
        self.assertIn("Было", resp.text)
        self.assertIn("Стало", resp.text)

    async def test_versions_unknown_product_404(self):
        resp = await self.client.get("/api/products/99999/versions")
        self.assertEqual(resp.status_code, 404)

    async def test_versions_unknown_version_404(self):
        product_id = await self._product_id()
        resp = await self.client.get(f"/api/products/{product_id}/versions/999")
        self.assertEqual(resp.status_code, 404)
