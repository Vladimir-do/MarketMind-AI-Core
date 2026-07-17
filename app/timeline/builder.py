"""Timeline event builder assembled from existing product tables."""

from __future__ import annotations

from datetime import datetime

from app.database import ApprovalRecord, PriceHistory, Product
from app.timeline.enums import (
    EVENT_GROUP_LABELS,
    EVENT_PRIORITY,
    EVENT_TYPE_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    TimelineEventGroup,
    TimelineEventType,
    TimelineSource,
    TimelineStatus,
)
from app.timeline.schemas import ProductHistoryEvent, TimelineFilter, TimelinePagination


_FILTER_GROUPS = {
    "all": None,
    "import": {TimelineEventGroup.IMPORT},
    "price": {TimelineEventGroup.PRICE},
    "stock": {TimelineEventGroup.STOCK},
    "ai": {TimelineEventGroup.AI},
    "decision": {TimelineEventGroup.DECISION},
    "manual": {TimelineEventGroup.MANUAL},
    "quality": {TimelineEventGroup.QUALITY},
    "system": {TimelineEventGroup.SYSTEM},
}

_FIELD_LABELS = {
    "product": "Карточка товара",
    "price": "Цена",
    "availability_status": "Наличие",
    "name": "Название",
    "title": "Название",
    "description": "Описание",
}


class ProductHistoryBuilder:
    """Build a product timeline without duplicating persisted journals."""

    def build(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        event_filter: str = "all",
        limit: int = 100,
        offset: int = 0,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort: str = "newest_first",
        source: str = "all",
        filters: TimelineFilter | None = None,
        pagination: TimelinePagination | None = None,
    ) -> list[ProductHistoryEvent]:
        filters = filters or TimelineFilter(
            event_type=event_filter,
            source=source,
            date_from=date_from,
            date_to=date_to,
        )
        pagination = pagination or TimelinePagination(limit=limit, offset=offset, sort=sort)

        events: list[ProductHistoryEvent] = []
        events.extend(self._import_events(product))
        events.extend(self._price_and_stock_events(product, price_history))
        events.extend(self._approval_events(product, approval_records))
        events, _warnings = self._deduplicate_events(events)
        events = self._filter_events(events, filters)
        events = self._sort_events(events, pagination.sort)
        return self._paginate_events(events, pagination)

    def build_with_warnings(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        filters: TimelineFilter,
        pagination: TimelinePagination,
    ) -> tuple[list[ProductHistoryEvent], list[str]]:
        events: list[ProductHistoryEvent] = []
        events.extend(self._import_events(product))
        events.extend(self._price_and_stock_events(product, price_history))
        events.extend(self._approval_events(product, approval_records))
        events, warnings = self._deduplicate_events(events)
        events = self._filter_events(events, filters)
        events = self._sort_events(events, pagination.sort)
        return self._paginate_events(events, pagination), warnings

    def _import_events(self, product: Product) -> list[ProductHistoryEvent]:
        if product.first_seen is None:
            return []
        return [
            self._event(
                event_id=f"product:{product.id}:import",
                product_id=product.id,
                event_type=TimelineEventType.PRODUCT_IMPORTED,
                event_group=TimelineEventGroup.IMPORT,
                source=TimelineSource.IMPORT,
                occurred_at=product.first_seen,
                field="product",
                old_value=None,
                new_value=product.name or product.url,
                reason="Товар впервые сохранён в каталоге",
            )
        ]

    def _price_and_stock_events(
        self,
        product: Product,
        price_history: list[PriceHistory],
    ) -> list[ProductHistoryEvent]:
        events: list[ProductHistoryEvent] = []
        ordered = sorted(
            [item for item in price_history if item.recorded_at is not None],
            key=lambda item: item.recorded_at,
        )
        previous: PriceHistory | None = None
        for item in ordered:
            if previous is None:
                previous = item
                continue
            if previous.price != item.price:
                events.append(
                    self._event(
                        event_id=f"price:{item.id}:price",
                        product_id=product.id,
                        event_type=TimelineEventType.PRICE_CHANGED,
                        event_group=TimelineEventGroup.PRICE,
                        source=TimelineSource.SYNC,
                        occurred_at=item.recorded_at,
                        field="price",
                        old_value=self._price_value(previous.price),
                        new_value=self._price_value(item.price),
                        reason="Изменилась цена товара",
                        related_entity_type="price_history",
                        related_entity_id=str(item.id),
                    )
                )
            if previous.availability_status != item.availability_status:
                events.append(
                    self._event(
                        event_id=f"price:{item.id}:stock",
                        product_id=product.id,
                        event_type=TimelineEventType.STOCK_CHANGED,
                        event_group=TimelineEventGroup.STOCK,
                        source=TimelineSource.SYNC,
                        occurred_at=item.recorded_at,
                        field="availability_status",
                        old_value=self._empty_dash(previous.availability_status),
                        new_value=self._empty_dash(item.availability_status),
                        reason="Изменился статус наличия товара",
                        related_entity_type="price_history",
                        related_entity_id=str(item.id),
                    )
                )
            previous = item
        return events

    def _approval_events(
        self,
        product: Product,
        approval_records: list[ApprovalRecord],
    ) -> list[ProductHistoryEvent]:
        events: list[ProductHistoryEvent] = []
        for record in approval_records:
            if record.created_at is not None:
                events.append(
                    self._event(
                        event_id=f"approval:{record.approval_id}:created",
                        product_id=product.id,
                        event_type=TimelineEventType.AI_SUGGESTION_CREATED,
                        event_group=TimelineEventGroup.AI,
                        source=TimelineSource.AI,
                        occurred_at=record.created_at,
                        field=record.field,
                        old_value=record.before_value,
                        new_value=record.after_value,
                        status=TimelineStatus.PENDING,
                        reason=record.reason,
                        confidence=record.confidence,
                        related_entity_type="approval",
                        related_entity_id=record.approval_id,
                    )
                )
            if record.reviewed_at is not None and record.status in {"approved", "rejected"}:
                is_rejected = record.status == "rejected"
                events.append(
                    self._event(
                        event_id=f"approval:{record.approval_id}:{record.status}",
                        product_id=product.id,
                        event_type=(
                            TimelineEventType.AI_SUGGESTION_REJECTED
                            if is_rejected
                            else TimelineEventType.AI_SUGGESTION_APPROVED
                        ),
                        event_group=TimelineEventGroup.DECISION,
                        source=TimelineSource.USER,
                        occurred_at=record.reviewed_at,
                        field=record.field,
                        old_value=record.before_value,
                        new_value=record.after_value,
                        status=TimelineStatus.REJECTED if is_rejected else TimelineStatus.APPROVED,
                        reason=record.reject_reason if is_rejected else record.reason,
                        confidence=record.confidence,
                        related_entity_type="approval",
                        related_entity_id=record.approval_id,
                    )
                )
            if record.applied_at is not None:
                events.append(
                    self._event(
                        event_id=f"approval:{record.approval_id}:applied",
                        product_id=product.id,
                        event_type=TimelineEventType.AI_SUGGESTION_APPLIED,
                        event_group=TimelineEventGroup.DECISION,
                        source=TimelineSource.USER,
                        occurred_at=record.applied_at,
                        field=record.field,
                        old_value=record.before_value,
                        new_value=record.after_value,
                        status=TimelineStatus.APPLIED,
                        reason="Одобренное предложение применено к товару",
                        confidence=record.confidence,
                        related_entity_type="approval",
                        related_entity_id=record.approval_id,
                    )
                )
            if record.rolled_back_at is not None:
                events.append(
                    self._event(
                        event_id=f"approval:{record.approval_id}:rolled_back",
                        product_id=product.id,
                        event_type=TimelineEventType.AI_SUGGESTION_ROLLED_BACK,
                        event_group=TimelineEventGroup.DECISION,
                        source=TimelineSource.USER,
                        occurred_at=record.rolled_back_at,
                        field=record.field,
                        old_value=record.after_value,
                        new_value=record.before_value,
                        status=TimelineStatus.ROLLED_BACK,
                        reason="Пользователь отменил ранее принятое решение",
                        confidence=record.confidence,
                        related_entity_type="approval",
                        related_entity_id=record.approval_id,
                    )
                )
        return events

    def _filter_events(
        self,
        events: list[ProductHistoryEvent],
        filters: TimelineFilter,
    ) -> list[ProductHistoryEvent]:
        allowed_groups = _FILTER_GROUPS.get(filters.event_type, _FILTER_GROUPS["all"])
        if allowed_groups is not None:
            events = [event for event in events if event.event_group in {item.value for item in allowed_groups}]
        if filters.source != "all":
            events = [event for event in events if event.source == filters.source]
        if filters.date_from is not None:
            events = [
                event
                for event in events
                if self._comparable_datetime(event.occurred_at)
                >= self._comparable_datetime(filters.date_from)
            ]
        if filters.date_to is not None:
            events = [
                event
                for event in events
                if self._comparable_datetime(event.occurred_at)
                <= self._comparable_datetime(filters.date_to)
            ]
        return events

    def _sort_events(self, events: list[ProductHistoryEvent], sort: str) -> list[ProductHistoryEvent]:
        reverse = sort != "oldest_first"
        events = list(events)
        events.sort(key=lambda event: event.event_id)
        events.sort(key=lambda event: EVENT_PRIORITY.get(TimelineEventType(event.event_type), 100))
        events.sort(key=lambda event: self._comparable_datetime(event.occurred_at), reverse=reverse)
        return events

    @staticmethod
    def _paginate_events(
        events: list[ProductHistoryEvent],
        pagination: TimelinePagination,
    ) -> list[ProductHistoryEvent]:
        safe_offset = max(pagination.offset, 0)
        safe_limit = max(pagination.limit, 0)
        return events[safe_offset : safe_offset + safe_limit]

    @staticmethod
    def _deduplicate_events(
        events: list[ProductHistoryEvent],
    ) -> tuple[list[ProductHistoryEvent], list[str]]:
        seen: set[str] = set()
        result: list[ProductHistoryEvent] = []
        warnings: list[str] = []
        for event in events:
            if event.event_id in seen:
                warnings.append(f"Дубликат события пропущен: {event.event_id}")
                continue
            seen.add(event.event_id)
            result.append(event)
        return result, warnings

    @staticmethod
    def _event(
        *,
        event_id: str,
        product_id: int,
        event_type: TimelineEventType,
        event_group: TimelineEventGroup,
        source: TimelineSource,
        occurred_at: datetime,
        field: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        status: TimelineStatus = TimelineStatus.RECORDED,
        reason: str | None = None,
        comment: str | None = None,
        confidence: float | None = None,
        related_entity_type: str | None = None,
        related_entity_id: str | None = None,
    ) -> ProductHistoryEvent:
        return ProductHistoryEvent(
            event_id=event_id,
            product_id=product_id,
            event_type=event_type.value,
            event_type_label=EVENT_TYPE_LABELS.get(event_type, event_type.value),
            event_group=event_group.value,
            event_group_label=EVENT_GROUP_LABELS.get(event_group, event_group.value),
            source=source.value,
            source_label=SOURCE_LABELS.get(source, source.value),
            occurred_at=occurred_at,
            status=status.value,
            status_label=STATUS_LABELS.get(status, status.value),
            field=field,
            field_label=_FIELD_LABELS.get(field or "", field),
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            comment=comment,
            confidence=confidence,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            related_id=related_entity_id,
        )

    @staticmethod
    def _price_value(value: int | None) -> str:
        return "—" if value is None else f"{value} ₽"

    @staticmethod
    def _empty_dash(value: str | None) -> str:
        return value if value else "—"

    @staticmethod
    def _comparable_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.replace(tzinfo=None)
