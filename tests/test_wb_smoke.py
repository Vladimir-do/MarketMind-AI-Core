import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import wb_smoke


class _FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.body


class _FakeSession:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        self.baskets: list[str] = []
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        self.baskets.append(url.split("basket-", 1)[1].split(".", 1)[0])
        return _FakeResponse(self.status, self.body)


class WBSmokeTests(unittest.TestCase):
    def test_cli_reaches_validation_without_pythonpath(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)

        result = subprocess.run(
            [sys.executable, str(repository_root / "scripts" / "wb_smoke.py"), "123"],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("от 6 до 12 цифр", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_missing_card_uses_same_unique_candidates_as_parser(self):
        session = _FakeSession(404, {})
        with patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session):
            exit_code = wb_smoke.main([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(session.baskets[0], "19")
        self.assertEqual(len(session.baskets), 80)
        self.assertEqual(len(session.baskets), len(set(session.baskets)))
        self.assertIn("/vol3118/part311895/311895731/info/ru/card.json", session.urls[0])

    def test_found_card_returns_zero_on_primary_basket(self):
        session = _FakeSession(200, {"imt_name": "Test product", "sizes": []})
        with patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session):
            exit_code = wb_smoke.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(session.baskets, ["19"])

    def test_found_card_reads_price_from_later_size(self):
        session = _FakeSession(
            200,
            {
                "imt_name": "Test product",
                "sizes": [
                    {"price": {}},
                    {"price": {"total": 123400, "basic": 159900}},
                ],
            },
        )
        output = io.StringIO()
        with (
            patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session),
            redirect_stdout(output),
        ):
            exit_code = wb_smoke.main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("Цена: 1234 руб.", output.getvalue())

    def test_http_200_without_product_name_is_not_success(self):
        session = _FakeSession(200, {"sizes": []})
        with patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session):
            exit_code = wb_smoke.main([])

        self.assertEqual(exit_code, 1)

    def test_invalid_product_id_is_rejected(self):
        with self.assertRaises(SystemExit):
            wb_smoke.main(["123"])


if __name__ == "__main__":
    unittest.main()
