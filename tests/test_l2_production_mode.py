import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.helpers import reload_app_modules


class L2ProductionModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        runtime_root = Path.cwd() / "runtime" / "l2_test_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="case_", dir=runtime_root)
        self.root = Path(self.tmp.name)
        self.home = self.root / "runtime"
        self._set_work_env(self.home)
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{(self.home / 'database' / 'marketmind.db').as_posix()}")
        self.db = database.Database()
        await self.db.init()

    async def asyncTearDown(self):
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
            "MARKETMIND_LOW_SPACE_BYTES",
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

    async def _create_project(self, name: str) -> str:
        from app.projects.service import ProjectService

        project = await ProjectService(self.db).create_project(name=name, client_name="Client", marketplace="ozon")
        return project.project_id

    async def _import_basic_csv(self, project_id: str, title: str, filename: str = "products.csv") -> None:
        from app.projects.imports import analyze_import_file, build_products_from_preview
        from app.projects.service import ProjectService
        from app.workspace.files import store_source_file

        content = f"Название,Цена,Ссылка\n{title},100,https://example.test/{title}\n".encode()
        stored = store_source_file(project_id, filename, content)
        preview = analyze_import_file(path=stored.absolute_path, original_filename=stored.original_filename, sha256=stored.sha256, size_bytes=stored.size_bytes, file_format=stored.file_format)
        products, errors = build_products_from_preview(preview, mapping=preview.suggested_mapping)
        self.assertFalse(errors)
        file_record, _ = await ProjectService(self.db).record_source_file(
            project_id,
            stored,
            row_count=preview.row_count,
            successful_rows=len(products),
            summary=preview.to_dict(),
        )
        for index, product in enumerate(products, start=1):
            saved, _ = await self.db.save_product(
                product.source_url or f"https://example.test/{title}/{index}",
                product.to_dict(),
            )
            await ProjectService(self.db).link_imported_product(project_id, saved, product, source_file_id=file_record.file_id, source_row_index=index)

    async def test_repeated_work_start_preserves_projects(self):
        project_id = await self._create_project("Persistent")
        await self.db._engine.dispose()
        _, database = reload_app_modules(os.environ["DATABASE_URL"])
        restarted = database.Database()
        await restarted.init()
        try:
            from app.projects.service import ProjectService

            project = await ProjectService(restarted).get_project(project_id)
            self.assertEqual(project.name, "Persistent")
        finally:
            await restarted._engine.dispose()
            _, database = reload_app_modules(os.environ["DATABASE_URL"])
            self.db = database.Database()
            await self.db.init()

    async def test_work_mode_uses_project_runtime_not_tmp(self):
        from app.runtime_paths import runtime_layout, system_status

        layout = runtime_layout()
        self.assertEqual(layout.home, self.home)
        self.assertNotIn("/tmp", layout.home.as_posix())
        status = await system_status(self.db)
        self.assertEqual(status["mode"]["mode"], "work")
        self.assertFalse([item for item in status["warnings"] if "/tmp" in item])

    async def test_backup_checksum_restore_and_protective_copy(self):
        project_id = await self._create_project("Before restore")
        from app.backups.service import create_database_backup, restore_database_backup, sha256_file
        from app.projects.service import ProjectService
        from app.runtime_paths import runtime_layout

        backup = create_database_backup(reason="test")
        self.assertEqual(backup["checksum"], sha256_file(Path(backup["path"])))
        await ProjectService(self.db).update_project(project_id, {"name": "After backup"})
        await self.db._engine.dispose()
        result = restore_database_backup(Path(backup["path"]).name, confirmation="ВОССТАНОВИТЬ")
        self.assertTrue(Path(result["protective_backup"]["path"]).exists())
        backups = list(runtime_layout().backups_dir.glob("*.db"))
        self.assertGreaterEqual(len(backups), 2)
        _, database = reload_app_modules(os.environ["DATABASE_URL"])
        restored_db = database.Database()
        await restored_db.init()
        try:
            restored = await ProjectService(restored_db).get_project(project_id)
            self.assertEqual(restored.name, "Before restore")
        finally:
            await restored_db._engine.dispose()
            _, database = reload_app_modules(os.environ["DATABASE_URL"])
            self.db = database.Database()
            await self.db.init()

    async def test_project_archive_contains_only_selected_project_and_no_secrets(self):
        project_a = await self._create_project("Archive A")
        project_b = await self._create_project("Archive B")
        await self._import_basic_csv(project_a, "Alpha", filename="alpha.csv")
        await self._import_basic_csv(project_b, "Beta", filename="beta.csv")

        from app.projects.archive import ProjectArchiveService
        from app.workspace.files import project_root

        (project_root(project_a) / ".env").write_text("PLACEHOLDER=redacted-value", encoding="utf-8")
        archive = await ProjectArchiveService(self.db).create_project_archive(project_a)
        with zipfile.ZipFile(archive["absolute_path"]) as zip_file:
            names = zip_file.namelist()
            payload = "\n".join(names) + "\n" + "\n".join(
                zip_file.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".json") or name.endswith(".csv") or name.endswith(".html")
            )
        self.assertIn("manifest.json", names)
        self.assertIn(project_a, payload)
        self.assertIn("Alpha", payload)
        self.assertNotIn(project_b, payload)
        self.assertNotIn("Beta", payload)
        self.assertNotIn(".env", payload)
        self.assertNotIn("redacted-value", payload)

    async def test_low_space_warning_is_reported(self):
        from collections import namedtuple

        from app.runtime_paths import system_status

        usage = namedtuple("usage", "total used free")(total=100, used=95, free=5)
        os.environ["MARKETMIND_LOW_SPACE_BYTES"] = "10"
        with patch("app.runtime_paths.shutil.disk_usage", return_value=usage):
            status = await system_status(self.db)
        self.assertTrue(any("мало свободного места" in warning for warning in status["warnings"]))

    async def test_demo_and_work_mode_banners_are_visually_distinct(self):
        from httpx import ASGITransport, AsyncClient

        from app.web.app import create_app

        work_app = create_app()
        work_app.state.db = self.db
        async with AsyncClient(transport=ASGITransport(app=work_app), base_url="http://testserver") as client:
            response = await client.get("/projects")
            self.assertIn("РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ", response.text)

        os.environ["MARKETMIND_MODE"] = "demo"
        _, database = reload_app_modules(os.environ["DATABASE_URL"])
        demo_app = create_app()
        demo_app.state.db = self.db
        async with AsyncClient(transport=ASGITransport(app=demo_app), base_url="http://testserver") as client:
            response = await client.get("/projects")
            self.assertIn("ДЕМОНСТРАЦИОННЫЙ РЕЖИМ. ДАННЫЕ МОГУТ БЫТЬ УДАЛЕНЫ", response.text)
        os.environ["MARKETMIND_MODE"] = "work"
        reload_app_modules(os.environ["DATABASE_URL"])
