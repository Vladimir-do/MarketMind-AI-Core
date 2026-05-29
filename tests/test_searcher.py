import unittest
from unittest.mock import patch

from app.searcher import (
    _mark_ozon_search_blocked,
    _reset_ozon_search_block_state,
    ozon_search_blocked_message,
)


class SearcherTests(unittest.TestCase):
    def tearDown(self):
        _reset_ozon_search_block_state()

    def test_ozon_search_block_message_after_mark(self):
        with patch.dict("os.environ", {"OZON_SEARCH_BLOCK_COOLDOWN_MINUTES": "2"}):
            _mark_ozon_search_blocked("abt-challenge/antibot")

        message = ozon_search_blocked_message()
        self.assertIsNotNone(message)
        self.assertIn("Поиск Ozon временно недоступен", message)
        self.assertIn("abt-challenge", message)

    def test_ozon_search_block_reset(self):
        _mark_ozon_search_blocked("blocked")
        _reset_ozon_search_block_state()

        self.assertIsNone(ozon_search_blocked_message())


if __name__ == "__main__":
    unittest.main()
