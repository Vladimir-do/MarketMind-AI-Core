from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.database import ApprovalRecord, PriceHistory, Product
from app.domain.events import (
    ApprovalEventBuilder,
    DomainEvent,
    EventActor,
    JsonEventSerializer,
    ProductEventBuilder,
    ReadModelEventReader,
)


def _dt(hour: int) -> datetime:
    return datetime(2026, 7, 17, hour, 0, tzinfo=UTC)


def test_domain_event_serializes_roundtrip():
    event = DomainEvent(
        event_id="product:1:imported",
        aggregate_type="product",
        aggregate_id="1",
        event_type="product.imported",
        source="import",
        actor=EventActor("system", display_name="Импорт"),
        occurred_at=_dt(10),
        payload={"name": "Товар"},
        metadata={"source_table": "products"},
        version=1,
    )

    serializer = JsonEventSerializer()
    restored = serializer.loads(serializer.dumps(event))

    assert restored == event
    assert restored.to_dict()["occurred_at"] == "2026-07-17T10:00:00+00:00"


def test_domain_event_rejects_sensitive_keys():
    event = DomainEvent(
        event_id="product:1:secret",
        aggregate_type="product",
        aggregate_id="1",
        event_type="product.imported",
        source="import",
        occurred_at=_dt(10),
        payload={"api_key": "do-not-store"},
    )

    with pytest.raises(ValueError, match="Sensitive key"):
        JsonEventSerializer().dumps(event)


def test_product_event_builder_import_price_and_stock_events():
    product = Product(
        id=1,
        url_hash="hash",
        url="https://example.test/1",
        name="Товар",
        image_url="https://example.test/image.jpg",
        first_seen=_dt(9),
    )
    history = [
        PriceHistory(id=10, product_id=1, price=100, availability_status="in_stock", recorded_at=_dt(10)),
        PriceHistory(id=11, product_id=1, price=150, availability_status="out_of_stock", recorded_at=_dt(11)),
    ]

    events = ProductEventBuilder().build_product_events(product, history)

    assert [event.event_type for event in events] == [
        "product.imported",
        "product.price_changed",
        "product.stock_changed",
    ]
    assert events[1].event_id == "price_history:11:price"
    assert events[1].payload["old_value"] == 100
    assert events[1].payload["new_value"] == 150
    assert events[2].payload["field"] == "availability_status"


def test_approval_event_builder_lifecycle_events():
    record = ApprovalRecord(
        approval_id="abc123",
        product_id="1",
        field="name",
        suggestion_type="improve",
        before_value="Старое",
        after_value="Новое",
        reason="Лучше читается",
        confidence=0.9,
        source_finding="name_short",
        status="rolled_back",
        created_at=_dt(9),
        reviewed_at=_dt(10),
        applied_at=_dt(11),
        rolled_back_at=_dt(12),
    )

    events = ApprovalEventBuilder().build(record)

    assert [event.event_type for event in events] == [
        "ai.suggestion_created",
        "approval.applied",
        "approval.rolled_back",
    ]
    assert events[-1].payload["old_value"] == "Новое"
    assert events[-1].payload["new_value"] == "Старое"


def test_approval_event_builder_approved_and_rejected_events():
    approved = ApprovalRecord(
        approval_id="approved1",
        product_id="1",
        field="name",
        suggestion_type="improve",
        before_value="A",
        after_value="B",
        reason="ok",
        confidence=0.8,
        status="approved",
        created_at=_dt(8),
        reviewed_at=_dt(9),
    )
    rejected = ApprovalRecord(
        approval_id="rejected1",
        product_id="1",
        field="description",
        suggestion_type="expand",
        before_value="A",
        after_value="B",
        reason="ok",
        reject_reason="Не подходит",
        confidence=0.7,
        status="rejected",
        created_at=_dt(8),
        reviewed_at=_dt(10),
    )

    events = ApprovalEventBuilder().build_approval_events([approved, rejected])
    event_types = [event.event_type for event in events]

    assert "approval.approved" in event_types
    assert "approval.rejected" in event_types
    rejected_event = next(event for event in events if event.event_type == "approval.rejected")
    assert rejected_event.payload["reason"] == "Не подходит"


def test_read_model_event_reader_filters_sorts_and_deduplicates():
    events = [
        DomainEvent(
            event_id="b",
            aggregate_type="product",
            aggregate_id="1",
            event_type="product.stock_changed",
            source="sync",
            occurred_at=_dt(11),
            payload={},
        ),
        DomainEvent(
            event_id="a",
            aggregate_type="product",
            aggregate_id="1",
            event_type="product.price_changed",
            source="sync",
            occurred_at=_dt(12),
            payload={},
        ),
        DomainEvent(
            event_id="a",
            aggregate_type="product",
            aggregate_id="1",
            event_type="product.price_changed",
            source="sync",
            occurred_at=_dt(12),
            payload={},
        ),
    ]

    reader = ReadModelEventReader(events)
    result = reader.list_events(aggregate_type="product", aggregate_id="1", limit=10)

    assert [event.event_id for event in result] == ["a", "b"]
    assert reader.list_events(event_type="product.stock_changed")[0].event_id == "b"
    assert reader.list_events(limit=1, offset=1)[0].event_id == "b"


def test_domain_event_reader_normalizes_timezone_for_sorting():
    same_utc = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    same_plus_five = datetime(2026, 7, 17, 12, 0, tzinfo=timezone(timedelta(hours=5)))
    later = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    reader = ReadModelEventReader(
        [
            DomainEvent(
                event_id="same-b",
                aggregate_type="product",
                aggregate_id="1",
                event_type="product.stock_changed",
                source="sync",
                occurred_at=same_plus_five,
                payload={},
            ),
            DomainEvent(
                event_id="later",
                aggregate_type="product",
                aggregate_id="1",
                event_type="product.price_changed",
                source="sync",
                occurred_at=later,
                payload={},
            ),
            DomainEvent(
                event_id="same-a",
                aggregate_type="product",
                aggregate_id="1",
                event_type="product.price_changed",
                source="sync",
                occurred_at=same_utc,
                payload={},
            ),
        ]
    )

    result = reader.list_events(sort="oldest_first")

    assert [event.event_id for event in result] == ["same-a", "same-b", "later"]
