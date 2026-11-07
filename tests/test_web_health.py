"""Liveness, readiness, and restrictive CORS regression tests."""

import os
import tempfile
import unittest
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from tests.helpers import reload_app_modules


class WebHealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "health.db"
        os.environ["CORS_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.db = database.Database()
        await self.db.init()
        from app.web.app import create_app

        self.app = create_app()
        self.app.state.db = self.db
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()
        os.environ.pop("CORS_ORIGINS", None)
        self.tmp.cleanup()

    async def test_health_is_liveness_only(self):
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_ready_checks_database(self):
        response = await self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "database": "ok"})

    async def test_ready_returns_503_without_database(self):
        app = self.app
        del app.state.db
        response = await self.client.get("/ready")
        self.assertEqual(response.status_code, 503)

    async def test_cors_allows_configured_origin(self):
        response = await self.client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "hx-current-url,hx-request",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:8000")
        self.assertIn("hx-current-url", response.headers.get("access-control-allow-headers", "").lower())
        self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")

    async def test_cors_rejects_unconfigured_origin(self):
        response = await self.client.options(
            "/health",
            headers={
                "Origin": "https://attacker.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", response.headers)

    async def test_cors_wildcard_never_enables_credentials(self):
        os.environ["CORS_ORIGINS"] = "*"
        from app.web.app import create_app

        wildcard_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=wildcard_app),
            base_url="http://testserver",
        ) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "https://public.example",
                    "Access-Control-Request-Method": "GET",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)


if __name__ == "__main__":
    unittest.main()
