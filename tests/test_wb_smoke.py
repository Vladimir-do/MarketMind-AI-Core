import unittest
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

    async def json(self):
        return self.body


class _FakeSession:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        self.baskets: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url: str, **kwargs):
        self.baskets.append(url.split("basket-", 1)[1].split(".", 1)[0])
        return _FakeResponse(self.status, self.body)


class WBSmokeTests(unittest.TestCase):
    def test_missing_card_returns_nonzero_and_uses_unique_baskets(self):
        session = _FakeSession(404, {})
        with patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session):
            exit_code = wb_smoke.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(len(session.baskets), 5)
        self.assertEqual(len(session.baskets), len(set(session.baskets)))

    def test_found_card_returns_zero(self):
        session = _FakeSession(200, {"imt_name": "Test product", "sizes": []})
        with patch.object(wb_smoke.aiohttp, "ClientSession", return_value=session):
            exit_code = wb_smoke.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(session.baskets, ["18"])


if __name__ == "__main__":
    unittest.main()
