"""Regression tests for P1 group WEB-ERR.

Two independent fixes, both covered here:

1. app/web/routes/system.py::restore_backup() used to dispose the current
   DB engine and only later attempt the actual restore. Any exception from
   restore_database_backup() OTHER than BackupError (e.g. OSError from a
   full disk, or sqlite3.Error from a corrupted backup file) left
   request.app.state.db pointing at an already-disposed engine -- every
   subsequent request across the whole web app would then fail until a
   process restart. The fix reorders the operation so app.state.db is only
   touched (and the old engine only disposed) after a confirmed successful
   restore.

2. app/web/app.py had no @app.exception_handler(Exception) at all. Several
   routes (product_detail.py, reports.py, and others) have no local
   try/except and relied entirely on Starlette's default, unstructured 500
   for anything a service layer raises. The fix adds one global handler
   that reuses the existing domain-error -> HTTP status mapping from
   app.web.routes.projects::_editor_error(), so e.g. a ProjectNotFoundError
   raised from ANY route becomes the same 404 it would via an explicit
   _editor_error() call -- and everything else still becomes a generic 500,
   without leaking exception text/traceback to the client.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.helpers import reload_app_modules


class GlobalExceptionHandlerTests(unittest.IsolatedAsyncioTestCase):
    """Covers fix #2 (app/web/app.py) in isolation, via throwaway probe
    routes mounted on the real create_app() app -- independent of whatever
    any specific existing route currently does or does not catch."""

    async def asyncSetUp(self):
        # Imported here, not at module top: other test files reload
        # app.projects.service / app.web.routes.projects via
        # tests.helpers.reload_app_modules() (importlib.reload), which
        # replaces the ProjectNotFoundError class object. A module-level
        # import in this file would bind a stale class, so isinstance()
        # inside _editor_error() (which always sees whatever's currently in
        # sys.modules) would silently stop matching depending on test order.
        from app.projects.service import ProjectNotFoundError
        from app.web.app import create_app

        self.app = create_app()

        probe_router = APIRouter()

        @probe_router.get("/__test_probe/not_found")
        async def _raise_not_found():
            raise ProjectNotFoundError("Проект не найден (тест)")

        @probe_router.get("/__test_probe/generic")
        async def _raise_generic():
            raise RuntimeError("boom-internal-detail (тест)")

        @probe_router.get("/__test_probe/http_exception")
        async def _raise_http_exception():
            raise HTTPException(status_code=418, detail="teapot (тест)")

        self.app.include_router(probe_router)
        # raise_app_exceptions=False: matches what a real HTTP client sees.
        # Starlette's ServerErrorMiddleware sends the response body produced
        # by an Exception-class handler and then always re-raises the
        # original exception (for ASGI-server-level logging) -- httpx's
        # ASGITransport surfaces that re-raise as a Python exception unless
        # told not to, which a real client over the wire never observes.
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False), base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_domain_not_found_error_maps_to_404_via_global_handler(self):
        response = await self.client.get("/__test_probe/not_found")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Проект не найден (тест)"})

    async def test_generic_exception_returns_structured_500_without_leaking_internals(self):
        response = await self.client.get("/__test_probe/generic")
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("detail", data)
        # The user-facing message must be the fixed, generic _editor_error()
        # text -- not the raw exception message or a traceback.
        self.assertNotIn("boom-internal-detail", response.text)
        self.assertNotIn("RuntimeError", response.text)
        self.assertNotIn("Traceback", response.text)

    async def test_http_exception_handling_is_unchanged(self):
        """The new catch-all Exception handler must not interfere with
        FastAPI's existing HTTPException handling."""
        response = await self.client.get("/__test_probe/http_exception")
        self.assertEqual(response.status_code, 418)
        self.assertEqual(response.json(), {"detail": "teapot (тест)"})


class RestoreBackupOrderingTests(unittest.IsolatedAsyncioTestCase):
    """Covers fix #1 (app/web/routes/system.py::restore_backup)."""

    async def asyncSetUp(self):
        runtime_root = Path.cwd() / "runtime" / "web_err_test_runtime"
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
        # raise_app_exceptions=False: matches what a real HTTP client sees.
        # Starlette's ServerErrorMiddleware sends the response body produced
        # by an Exception-class handler and then always re-raises the
        # original exception (for ASGI-server-level logging) -- httpx's
        # ASGITransport surfaces that re-raise as a Python exception unless
        # told not to, which a real client over the wire never observes.
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

    async def test_non_backup_error_leaves_app_state_db_usable(self):
        """Regression for WEB-ERR / restore_backup ordering bug: before the
        fix, a non-BackupError exception from restore_database_backup() left
        request.app.state.db pointing at an already-disposed engine. Every
        subsequent request would then fail -- not just this one."""
        original_db = self.app.state.db

        with patch(
            "app.web.routes.system.restore_database_backup",
            side_effect=OSError("disk full (test)"),
        ):
            response = await self.client.post(
                "/system/backups/whatever.db/restore",
                data={"confirmation": "ВОССТАНОВИТЬ"},
            )

        # Not a BackupError -> falls through to the global handler -> 500,
        # generic message, no leaked exception text.
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("disk full", response.text)

        # app.state.db must be untouched (same object, not swapped/disposed).
        self.assertIs(self.app.state.db, original_db)

        # And it must still be a live, usable engine -- proves dispose() was
        # never called on it.
        async with self.app.state.db.session() as session:
            result = await session.execute(text("SELECT 1"))
            self.assertEqual(result.scalar(), 1)

    async def test_backup_error_still_returns_422_as_before(self):
        """Existing behavior for the validation-style BackupError case must
        be unchanged by the reordering."""
        response = await self.client.post(
            "/system/backups/does-not-exist.db/restore",
            data={"confirmation": "ВОССТАНОВИТЬ"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("не найдена", response.json()["detail"].lower())

    async def test_successful_restore_still_swaps_db_and_redirects(self):
        """Normal success path must behave exactly as before the reordering."""
        from app.backups.service import create_database_backup
        from app.projects.service import ProjectService

        project = await ProjectService(self.db).create_project(name="Before restore")
        project_id = project.project_id
        backup = create_database_backup(reason="test")
        await ProjectService(self.db).update_project(project_id, {"name": "After backup"})

        response = await self.client.post(
            f"/system/backups/{Path(backup['path']).name}/restore",
            data={"confirmation": "ВОССТАНОВИТЬ"},
        )

        self.assertEqual(response.status_code, 303)

        restored_project = await ProjectService(self.app.state.db).get_project(project_id)
        self.assertEqual(restored_project.name, "Before restore")

        # The route-swapped db is now the one asyncTearDown should dispose,
        # not the original -- keep self.db pointed at the live instance so
        # teardown disposes the right engine.
        self.db = self.app.state.db


if __name__ == "__main__":
    unittest.main()
