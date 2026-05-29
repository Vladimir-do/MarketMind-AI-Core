import tempfile
import unittest
from pathlib import Path

from tools.defrag_audit import build_report


class DefragAuditTests(unittest.TestCase):
    def test_report_detects_large_modules_runtime_dirs_and_duplicate_envs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "bot.py").write_text("print('x')\n" * 10, encoding="utf-8")
            (root / "app" / "small.py").write_text("x = 1\n", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / "venv").mkdir()
            (root / ".ozon_profile").mkdir()
            (root / ".ozon_profile" / "cache.bin").write_bytes(b"x" * 128)
            (root / "report.html").write_text("<html></html>", encoding="utf-8")

            report = build_report(root, limit=2)

        self.assertEqual(report.duplicate_envs, [".venv", "venv"])
        self.assertEqual(report.largest_python[0].path, "app/bot.py")
        self.assertEqual(report.largest_python[0].lines, 10)
        self.assertEqual(report.runtime_dirs[0].path, ".ozon_profile")
        self.assertEqual(report.runtime_dirs[0].bytes, 128)
        self.assertEqual(report.loose_artifacts[0].path, "report.html")


if __name__ == "__main__":
    unittest.main()
