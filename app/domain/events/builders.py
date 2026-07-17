"""Read-model builders that convert existing records into DomainEvents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.database import Product
from app.domain.events.models import AggregateType, DomainEvent, EventActor, EventSource
from app.domain.events.time import event_sort_key

if TYPE_CHECKING:
    from datetime import datetime

    from app.database import ApprovalRecord, PriceHistory


class ProductEventBuilder:
    """Build product domain events from Product and PriceHistory rows."""

    def build_import_event(self, product: Product) -> DomainEvent | None:
        if product.first_seen is None:
            return None
        return DomainEvent(
            event_id=f"product:{product.id}:imported",
            aggregate_type=AggregateType.PRODUCT.value,
            aggregate_id=str(product.id),
            event_type="product.imported",
            source=EventSource.IMPORT.value,
            actor=EventActor("system", display_name="Импорт"),
            occurred_at=product.first_seen,
            payload={
                "name": product.name,
                "url": product.url,
                "image_url": product.image_url,
            },
            metadata={"source_table": "products"},
        )

    def build_price_events(
        self,
        product: Product,
        price_history: list[PriceHistory],
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        ordered = sorted(
            [item for item in price_history if item.recorded_at is not None],
            key=lambda item: event_sort_key(item.recorded_at),
        )
        previous: PriceHistory | None = None
        for item in ordered:
            if previous is None:
                previous = item
                continue
            if previous.price != item.price:
                events.append(
                    self._price_event(
                        product=product,
                        item=item,
                        event_type="product.price_changed",
                        field="price",
                        old_value=previous.price,
                        new_value=item.price,
                    )
                )
            if previous.availability_status != item.availability_status:
                events.append(
                    self._price_event(
                        product=product,
                        item=item,
                        event_type="product.stock_changed",
                        field="availability_status",
                        old_value=previous.availability_status,
                        new_value=item.availability_status,
                    )
                )
            previous = item
        return events

    def build_product_events(
        self,
        product: Product,
        price_history: list[PriceHistory],
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        imported = self.build_import_event(product)
        if imported is not None:
            events.append(imported)
        events.extend(self.build_price_events(product, price_history))
        return events

    def build(self, source: object) -> list[DomainEvent]:
        if isinstance(source, Product):
            imported = self.build_import_event(source)
            return [imported] if imported else []
        return []

    def _price_event(
        self,
        *,
        product: Product,
        item: PriceHistory,
        event_type: str,
        field: str,
        old_value: int | str | None,
        new_value: int | str | None,
    ) -> DomainEvent:
        suffix = "price" if field == "price" else "stock"
        return DomainEvent(
            event_id=f"price_history:{item.id}:{suffix}",
            aggregate_type=AggregateType.PRODUCT.value,
            aggregate_id=str(product.id),
            event_type=event_type,
            source=EventSource.SYNC.value,
            actor=EventActor("worker", display_name="Синхронизация"),
            occurred_at=item.recorded_at,
            payload={
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "price_history_id": item.id,
            },
            metadata={
                "source_table": "price_history",
                "product_url": product.url,
            },
        )


class ApprovalEventBuilder:
    """Build approval and AI domain events from ApprovalRecord rows."""

    def build_approval_events(self, records: list[ApprovalRecord]) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for record in records:
            events.extend(self.build(record))
        return events

    def build(self, source: object) -> list[DomainEvent]:
        if not hasattr(source, "approval_id"):
            return []
        record = source
        events: list[DomainEvent] = []
        if record.created_at is not None:
            events.append(self._event(record, "ai.suggestion_created", EventSource.AI.value, record.created_at))
        if record.reviewed_at is not None and record.status in {"approved", "rejected"}:
            events.append(
                self._event(
                    record,
                    f"approval.{record.status}",
                    EventSource.USER.value,
                    record.reviewed_at,
                    status=record.status,
                    reason=record.reject_reason if record.status == "rejected" else record.reason,
                )
            )
        if record.applied_at is not None:
            events.append(
                self._event(
                    record,
                    "approval.applied",
                    EventSource.USER.value,
                    record.applied_at,
                    status="applied",
                )
            )
        if record.rolled_back_at is not None:
            events.append(
                self._event(
                    record,
                    "approval.rolled_back",
                    EventSource.USER.value,
                    record.rolled_back_at,
                    status="rolled_back",
                    old_value=record.after_value,
                    new_value=record.before_value,
                )
            )
        return events

    def _event(
        self,
        record: ApprovalRecord,
        event_type: str,
        source: str,
        occurred_at: datetime,
        *,
        status: str | None = None,
        reason: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
    ) -> DomainEvent:
        action = event_type.rsplit(".", maxsplit=1)[-1]
        return DomainEvent(
            event_id=f"approval:{record.approval_id}:{action}",
            aggregate_type=AggregateType.APPROVAL.value,
            aggregate_id=record.approval_id,
            event_type=event_type,
            source=source,
            actor=EventActor("ai" if source == EventSource.AI.value else "user"),
            occurred_at=occurred_at,
            payload={
                "product_id": record.product_id,
                "field": record.field,
                "suggestion_type": record.suggestion_type,
                "old_value": record.before_value if old_value is None else old_value,
                "new_value": record.after_value if new_value is None else new_value,
                "reason": record.reason if reason is None else reason,
                "confidence": record.confidence,
                "status": status or record.status,
            },
            metadata={
                "source_table": "approval_records",
                "approval_id": record.approval_id,
                "source_finding": record.source_finding,
            },
        )
