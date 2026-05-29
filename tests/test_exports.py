import tempfile
import unittest
import asyncio
from pathlib import Path

from sqlalchemy import event

from tests.helpers import reload_app_modules


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "export_test.db"
        _, database = reload_app_modules(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        self.db = database.Database()
        await self.db.init()
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            {
                "name": "Bluetooth Headphones",
                "price": 1500,
                "availability": "in_stock",
                "image_url": "//basket-19.wb.ru/vol3118/part311895/311895731/images/big/1.webp",
            },
        )
        await self.db.save_product(
            "https://www.wildberries.ru/catalog/311895731/detail.aspx",
            {
                "name": "Bluetooth Headphones",
                "price": 1400,
                "availability": "in_stock",
                "image_url": "//basket-19.wb.ru/vol3118/part311895/311895731/images/big/1.webp",
            },
        )

    async def asyncTearDown(self):
        await self.db._engine.dispose()
        self.tmp.cleanup()

    async def test_csv_excel_and_html_exports_are_generated(self):
        from app.exporter import export_csv, export_excel
        from app.reporter import collect_report_data, export_html_report

        csv_buf = await export_csv(self.db)
        xlsx_buf = await export_excel(self.db)
        html_buf = await export_html_report(self.db)
        report_data = await collect_report_data(self.db)

        self.assertGreater(len(csv_buf.read()), 100)
        self.assertGreater(len(xlsx_buf.read()), 1000)
        self.assertGreater(len(html_buf.read()), 1000)
        self.assertEqual(report_data["total_products"], 1)
        self.assertEqual(len(report_data["products"]), 1)
        self.assertEqual(
            report_data["products"][0]["image_url"],
            "https://basket-19.wb.ru/vol3118/part311895/311895731/images/big/1.webp",
        )
        self.assertIn(b'<img src="https://basket-19.wb.ru', html_buf.getvalue())

    async def test_export_data_uses_batched_price_history_queries(self):
        from app.exporter import get_export_data

        for idx in range(5):
            url = f"https://example.test/product/{idx}"
            await self.db.save_product(
                url,
                {"name": f"Product {idx}", "price": 1000 + idx, "availability": "in_stock"},
            )
            await self.db.save_product(
                url,
                {"name": f"Product {idx}", "price": 900 + idx, "availability": "in_stock"},
            )

        select_count = 0

        def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        event.listen(self.db._engine.sync_engine, "before_cursor_execute", count_selects)
        try:
            rows = await get_export_data(self.db)
        finally:
            event.remove(self.db._engine.sync_engine, "before_cursor_execute", count_selects)

        self.assertEqual(len(rows), 6)
        self.assertLessEqual(select_count, 3)

    async def test_price_agent_analytics_use_batched_history_queries(self):
        from app.agent import PriceAgent

        for idx in range(5):
            url = f"https://example.test/agent-product/{idx}"
            await self.db.save_product(
                url,
                {"name": f"Agent Product {idx}", "price": 1000 + idx, "availability": "in_stock"},
            )
            await self.db.save_product(
                url,
                {"name": f"Agent Product {idx}", "price": 700 + idx, "availability": "in_stock"},
            )

        select_count = 0

        def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        agent = PriceAgent(self.db)
        event.listen(self.db._engine.sync_engine, "before_cursor_execute", count_selects)
        try:
            anomalies = await agent.detect_anomalies()
            deals = await agent.find_best_deals()
        finally:
            event.remove(self.db._engine.sync_engine, "before_cursor_execute", count_selects)

        self.assertGreaterEqual(len(anomalies), 5)
        self.assertGreaterEqual(len(deals), 5)
        self.assertLessEqual(select_count, 4)
