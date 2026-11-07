"""Regression tests for D24 (app/web/routes/import_.py::import_file).

Root cause: on ImportPipeline failure, import_file() returned
ImportResult(status="failed", ...) via a plain FastAPI `return`/
TemplateResponse with no explicit status_code -- both paths defaulted to
HTTP 200. A non-HTMX client checking the HTTP status code (rather than the
`status` field in the body) would read a failed import as a success.

Fix: _import_result_response() takes an `error` flag. For a JSON client
(no HX-Request header) on the error path, it now returns
JSONResponse(status_code=422, content=result.model_dump()) -- body shape
unchanged, status="failed" preserved. The HTMX path (HX-Request: true) is
untouched: still HTTP 200 + the existing import_result.html fragment, since
HTMX reads the rendered body, not the status code. The success path is
untouched in both cases.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from tests.helpers import reload_app_modules


class ImportFileErrorStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        runtime_root = Path.cwd() / "runtime" / "d24_test_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="case_", dir=runtime_root)
        self.root = Path(self.tmp.name)
        self.home = self.root / "runtime"
        self._set_work_env(self.home)
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{(self.home / 'database' / 'marketmind.db').as_posix()}")
        self.db = database.Database()
        await self.db.init()

        from app.web.app import create_app

        self.app = create_app()
        self.app.state.db = self.db
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False), base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.db._engine.dispose()
        for key in (
            "MARKETMIND_HOME",
            "MARKETMIND_MODE",
            "MARKETMIND_DATA_DIR",
            "MARKETMIND_WORKSPACE_DIR",
            "DATABASE_URL",
            "LOG_FILE",
            "SCRAPE_ATTEMPTS_JSONL",
            "BLOCK_PATTERNS_JSONL",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def _set_work_env(self, home: Path):
        os.environ["MARKETMIND_HOME"] = home.as_posix()
        os.environ["MARKETMIND_MODE"] = "work"
        os.environ["MARKETMIND_DATA_DIR"] = home.as_posix()
        os.environ["MARKETMIND_WORKSPACE_DIR"] = home.as_posix()
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(home / 'database' / 'marketmind.db').as_posix()}"
        os.environ["LOG_FILE"] = (home / "logs" / "marketmind.log").as_posix()
        os.environ["SCRAPE_ATTEMPTS_JSONL"] = (home / "logs" / "scrape_attempts.jsonl").as_posix()
        os.environ["BLOCK_PATTERNS_JSONL"] = (home / "logs" / "blocked_patterns.jsonl").as_posix()

    async def test_plain_client_gets_422_on_import_failure(self):
        with patch("app.pipeline.ImportPipeline.run_file", side_effect=RuntimeError("boom (test)")):
            response = await self.client.post(
                "/api/import/file",
                files={"file": ("products.csv", b"name,price\nX,100\n", "text/csv")},
            )

        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["status"], "failed")
        self.assertIn("boom (test)", data["message"])

    async def test_htmx_client_still_gets_200_on_import_failure(self):
        with patch("app.pipeline.ImportPipeline.run_file", side_effect=RuntimeError("boom (test)")):
            response = await self.client.post(
                "/api/import/file",
                files={"file": ("products.csv", b"name,price\nX,100\n", "text/csv")},
                headers={"HX-Request": "true"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("boom (test)", response.text)

    async def test_successful_import_stays_200_completed(self):
        csv_bytes = "название,бренд,цена\nКроссовки RunMax,RunMax,4500\n".encode()

        response = await self.client.post(
            "/api/import/file",
            files={"file": ("products.csv", csv_bytes, "text/csv")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["total_products"], 1)


if __name__ == "__main__":
    unittest.main()
