import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests.helpers import reload_app_modules


class WebApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "web_test.db"
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = str(Path(self.tmp.name) / "scrape_attempts.jsonl")
        os.environ["BLOCK_PATTERNS_JSONL"] = str(Path(self.tmp.name) / "blocked_patterns.jsonl")
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.database_module = database
        self.db = database.Database()
        await self.db.init()

        # Seed a product
        await self.db.save_product(
            "https://www.ozon.ru/product/123",
            {"name": "Тестовый товар", "price": 1500, "availability": "in_stock"},
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/456",
            {"name": "Другой товар", "price": 2000, "availability": "in_stock"},
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

    async def test_app_creation(self):
        from app.web.app import create_app

        app = create_app()
        self.assertIsNotNone(app)

    async def test_lifespan_closes_ai_clients(self):
        from app.web.app import create_app

        app = create_app()
        fake_db = Mock()
        fake_db.init = AsyncMock()
        fake_db._engine.dispose = AsyncMock()
        close_clients = AsyncMock()
        with (
            patch("app.database.Database", return_value=fake_db),
            patch("app.ai_client.close_ai_clients", close_clients),
        ):
            async with app.router.lifespan_context(app):
                self.assertIs(app.state.db, fake_db)

        close_clients.assert_awaited_once()
        fake_db._engine.dispose.assert_awaited_once()

    async def test_dashboard_endpoint(self):
        resp = await self.client.get("/api/dashboard")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_products"], 2)
        self.assertIsInstance(data["products_by_marketplace"], list)
        self.assertIsInstance(data["health_summary"], dict)

    async def test_products_endpoint(self):
        resp = await self.client.get("/api/products")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        names = {p["name"] for p in data}
        self.assertIn("Тестовый товар", names)

    async def test_products_search(self):
        resp = await self.client.get("/api/products?q=Тестовый")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Тестовый товар")

    async def test_dashboard_page(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("MarketMind", resp.text)

    async def test_products_page(self):
        resp = await self.client.get("/products")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Тестовый товар", resp.text)

    async def test_import_page(self):
        resp = await self.client.get("/import")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Импорт", resp.text)
        self.assertIn("Сохранённые товары", resp.text)
        self.assertIn("Тестовый товар", resp.text)

    async def test_import_demo_htmx_response_is_html(self):
        resp = await self.client.post("/api/import/demo", headers={"HX-Request": "true"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("Загружено", resp.text)
        self.assertNotIn('"task_id"', resp.text)
