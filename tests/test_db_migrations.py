import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import reload_app_modules


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "migrations.db"
        self.database_url = f"sqlite+aiosqlite:///{self.db_path.as_posix()}"
        reload_app_modules(self.database_url)

    def tearDown(self):
        os.environ.pop("DATABASE_URL", None)
        self.tmp.cleanup()

    def test_migration_status_reports_uninitialized_sqlite_database(self):
        from app.db_migrations import migration_status

        status = migration_status(self.database_url)

        self.assertEqual(status.current_revision, "not initialized")
        self.assertNotEqual(status.head_revision, "none")
        self.assertFalse(status.is_current)

    def test_upgrade_database_applies_head_revision(self):
        from app.db_migrations import migration_head, migration_status, upgrade_database

        upgraded = upgrade_database(self.database_url)
        status = migration_status(self.database_url)

        self.assertEqual(upgraded.current_revision, migration_head(self.database_url))
        self.assertTrue(upgraded.is_current)
        self.assertEqual(status.current_revision, upgraded.head_revision)
        self.assertTrue(status.is_current)

    def test_non_sqlite_current_revision_is_unknown_without_connection(self):
        from app.db_migrations import current_revision

        revision = current_revision("postgresql+asyncpg://user:pass@localhost/marketmind")

        self.assertEqual(revision, "unknown")
