import unittest
from datetime import UTC, datetime, timedelta, timezone

from app.database import ApprovalRecord, PriceHistory, Product
from app.timeline.builder import ProductHistoryBuilder
from app.timeline.schemas import TimelineFilter, TimelinePagination


class TimelineEngineTests(unittest.TestCase):
    def setUp(self):
        self.product = Product(
            id=7,
            url_hash="hash",
            url="https://example.com/product",
            name="Товар",
            image_url=None,
            first_seen=datetime(2026, 7, 17, 10, 0, 0),
        )
        self.builder = ProductHistoryBuilder()

    def test_builds_price_and_stock_events_without_import_duplication(self):
        rows = [
            PriceHistory(
                id=1,
                product_id=7,
                price=1000,
                availability_status="in_stock",
                recorded_at=datetime(2026, 7, 17, 10, 0, 0),
            ),
            PriceHistory(
                id=2,
                product_id=7,
                price=1200,
                availability_status="out_of_stock",
                recorded_at=datetime(2026, 7, 17, 11, 0, 0),
            ),
        ]

        events = self.builder.build(
            product=self.product,
            price_history=rows,
            approval_records=[],
            sort="oldest_first",
        )

        event_ids = [event.event_id for event in events]
        self.assertEqual(event_ids.count("product:7:import"), 1)
        self.assertIn("price:2:price", event_ids)
        self.assertIn("price:2:stock", event_ids)

    def test_same_timestamp_uses_priority_order(self):
        timestamp = datetime(2026, 7, 17, 12, 0, 0)
        rows = [
            PriceHistory(
                id=1,
                product_id=7,
                price=1000,
                availability_status="in_stock",
                recorded_at=datetime(2026, 7, 17, 10, 0, 0),
            ),
            PriceHistory(
                id=2,
                product_id=7,
                price=1200,
                availability_status="out_of_stock",
                recorded_at=timestamp,
            ),
        ]
        approvals = [
            ApprovalRecord(
                id=1,
                approval_id="abc",
                product_id="7",
                field="name",
                suggestion_type="rewrite",
                before_value="Старое",
                after_value="Новое",
                reason="Причина",
                confidence=0.9,
                status="approved",
                created_at=timestamp,
                reviewed_at=timestamp,
            )
        ]

        events = self.builder.build(
            product=self.product,
            price_history=rows,
            approval_records=approvals,
        )

        same_time = [
            event.event_type
            for event in events
            if event.occurred_at.astimezone(UTC).replace(tzinfo=None) == timestamp
        ]
        self.assertLess(
            same_time.index("ai_suggestion_approved"),
            same_time.index("ai_suggestion_created"),
        )
        self.assertLess(same_time.index("ai_suggestion_created"), same_time.index("price_changed"))
        self.assertLess(same_time.index("price_changed"), same_time.index("stock_changed"))

    def test_source_filter(self):
        rows = [
            PriceHistory(
                id=1,
                product_id=7,
                price=1000,
                availability_status="in_stock",
                recorded_at=datetime(2026, 7, 17, 10, 0, 0),
            ),
            PriceHistory(
                id=2,
                product_id=7,
                price=1200,
                availability_status="in_stock",
                recorded_at=datetime(2026, 7, 17, 11, 0, 0),
            ),
        ]

        events = self.builder.build(
            product=self.product,
            price_history=rows,
            approval_records=[],
            filters=TimelineFilter(source="sync"),
            pagination=TimelinePagination(limit=10),
        )

        self.assertEqual({event.source for event in events}, {"sync"})

    def test_deduplicates_by_event_id_with_warning(self):
        duplicate_a = ApprovalRecord(
            id=1,
            approval_id="dup",
            product_id="7",
            field="name",
            suggestion_type="rewrite",
            before_value="A",
            after_value="B",
            reason="Reason",
            confidence=0.8,
            status="pending",
            created_at=datetime(2026, 7, 17, 10, 0, 0),
        )
        duplicate_b = ApprovalRecord(
            id=2,
            approval_id="dup",
            product_id="7",
            field="name",
            suggestion_type="rewrite",
            before_value="A",
            after_value="B",
            reason="Reason",
            confidence=0.8,
            status="pending",
            created_at=datetime(2026, 7, 17, 10, 0, 0),
        )

        events, warnings = self.builder.build_with_warnings(
            product=self.product,
            price_history=[],
            approval_records=[duplicate_a, duplicate_b],
            filters=TimelineFilter(),
            pagination=TimelinePagination(limit=10),
        )

        event_ids = [event.event_id for event in events]
        self.assertEqual(event_ids.count("approval:dup:created"), 1)
        self.assertTrue(warnings)

    def test_timezone_sort_uses_same_instant(self):
        utc_time = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
        yekaterinburg_time = datetime(2026, 7, 17, 12, 0, tzinfo=timezone(timedelta(hours=5)))
        rows = [
            PriceHistory(
                id=1,
                product_id=7,
                price=1000,
                availability_status="in_stock",
                recorded_at=datetime(2026, 7, 17, 6, 0, tzinfo=UTC),
            ),
            PriceHistory(
                id=2,
                product_id=7,
                price=1100,
                availability_status="in_stock",
                recorded_at=yekaterinburg_time,
            ),
        ]
        approvals = [
            ApprovalRecord(
                id=1,
                approval_id="tz",
                product_id="7",
                field="name",
                suggestion_type="rewrite",
                before_value="A",
                after_value="B",
                reason="R",
                confidence=0.9,
                status="pending",
                created_at=utc_time,
            )
        ]

        events = self.builder.build(
            product=self.product,
            price_history=rows,
            approval_records=approvals,
            sort="oldest_first",
        )

        same_instant = [
            event.event_type
            for event in events
            if event.occurred_at == utc_time
        ]
        self.assertEqual(same_instant, ["ai_suggestion_created", "price_changed"])


if __name__ == "__main__":
    unittest.main()
