"""Timeline builder assembled from Domain Events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.events.builders import ApprovalEventBuilder, ProductEventBuilder
from app.domain.events.time import event_sort_key
from app.timeline.enums import EVENT_PRIORITY, TimelineEventType
from app.timeline.mapper import TimelineEventMapper
from app.timeline.schemas import ProductHistoryEvent, TimelineFilter, TimelinePagination

if TYPE_CHECKING:
    from datetime import datetime

    from app.database import ApprovalRecord, PriceHistory, Product
    from app.domain.events.models import DomainEvent


_FILTER_GROUPS = {
    "all": None,
    "import": {"import"},
    "price": {"price"},
    "stock": {"stock"},
    "ai": {"ai"},
    "decision": {"decision"},
    "manual": {"manual"},
    "quality": {"quality"},
    "system": {"system"},
}


class ProductHistoryBuilder:
    """Build a product timeline through the Domain Event contract."""

    def __init__(
        self,
        product_builder: ProductEventBuilder | None = None,
        approval_builder: ApprovalEventBuilder | None = None,
        mapper: TimelineEventMapper | None = None,
    ) -> None:
        self._product_builder = product_builder or ProductEventBuilder()
        self._approval_builder = approval_builder or ApprovalEventBuilder()
        self._mapper = mapper or TimelineEventMapper()

    def build(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        persisted_events: list[DomainEvent] | None = None,
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
        events, _warnings = self.build_with_warnings(
            product=product,
            price_history=price_history,
            approval_records=approval_records,
            persisted_events=persisted_events or [],
            filters=filters,
            pagination=pagination,
        )
        return events

    def build_with_warnings(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        filters: TimelineFilter,
        pagination: TimelinePagination,
        persisted_events: list[DomainEvent] | None = None,
    ) -> tuple[list[ProductHistoryEvent], list[str]]:
        domain_events = self._domain_events(
            product=product,
            price_history=price_history,
            approval_records=approval_records,
            persisted_events=persisted_events or [],
        )
        history_events = self._mapper.to_history_events(domain_events)
        history_events, warnings = self._deduplicate_events(history_events)
        history_events = self._filter_events(history_events, filters)
        history_events = self._sort_events(history_events, pagination.sort)
        return self._paginate_events(history_events, pagination), warnings

    def _domain_events(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        persisted_events: list[DomainEvent],
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        events.extend(self._product_builder.build_product_events(product, price_history))
        events.extend(self._approval_builder.build_approval_events(approval_records))
        events.extend(persisted_events)
        return events

    def _filter_events(
        self,
        events: list[ProductHistoryEvent],
        filters: TimelineFilter,
    ) -> list[ProductHistoryEvent]:
        allowed_groups = _FILTER_GROUPS.get(filters.event_type, _FILTER_GROUPS["all"])
        if allowed_groups is not None:
            events = [event for event in events if event.event_group in allowed_groups]
        if filters.source != "all":
            events = [event for event in events if event.source == filters.source]
        if filters.date_from is not None:
            date_from = event_sort_key(filters.date_from)
            events = [event for event in events if event_sort_key(event.occurred_at) >= date_from]
        if filters.date_to is not None:
            date_to = event_sort_key(filters.date_to)
            events = [event for event in events if event_sort_key(event.occurred_at) <= date_to]
        return events

    def _sort_events(self, events: list[ProductHistoryEvent], sort: str) -> list[ProductHistoryEvent]:
        reverse = sort != "oldest_first"
        events = list(events)
        events.sort(key=lambda event: event.event_id)
        events.sort(key=lambda event: EVENT_PRIORITY.get(TimelineEventType(event.event_type), 100))
        events.sort(key=lambda event: event_sort_key(event.occurred_at), reverse=reverse)
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
