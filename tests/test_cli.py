import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import main


class CliTests(unittest.TestCase):
    def test_main_without_mode_prints_help(self):
        buf = io.StringIO()
        with patch.object(sys, "argv", ["main.py"]), redirect_stdout(buf):
            main()
        output = buf.getvalue()
        self.assertIn("--telegram", output)
        self.assertIn("--update", output)
        self.assertIn("--blocks", output)

    def test_telegram_mode_returns_cleanly_when_startup_is_handled_failure(self):
        async_start = AsyncMock(return_value=False)
        buf = io.StringIO()

        with (
            patch.object(sys, "argv", ["main.py", "--telegram"]),
            patch("app.bot.start_bot", async_start),
            redirect_stdout(buf),
        ):
            main()

        async_start.assert_awaited_once()
        self.assertIn("Telegram bot was not started", buf.getvalue())

    def test_report_mode_passes_embed_images_flag(self):
        fake_db = MagicMock()
        fake_db.init = AsyncMock()
        fake_db._engine.dispose = AsyncMock()

        fake_report = io.BytesIO(b"<html></html>")
        fake_export = AsyncMock(return_value=fake_report)

        with (
            patch.object(sys, "argv", ["main.py", "--report", "--embed-images"]),
            patch("app.database.Database", return_value=fake_db),
            patch("app.reporter.export_html_report", fake_export),
            redirect_stdout(io.StringIO()),
        ):
            main()

        fake_export.assert_awaited_once_with(fake_db, embed_images=True)
