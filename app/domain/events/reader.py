"""Read-model event reader utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.events.time import event_sort_key

if TYPE_CHECKING:
    from app.domain.events.models import DomainEvent


class ReadModelEventReader:
    """Filters and orders in-memory DomainEvent streams.

    This is intentionally not a database repository. It supports the current
    read-model approach while keeping the public reader contract stable for a
    later persisted event store.
    """

    def __init__(self, events: list[DomainEvent]) -> None:
        self._events = self._deduplicate(events)

    def list_events(
        self,
        *,
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "newest_first",
    ) -> list[DomainEvent]:
        events = list(self._events)
        if aggregate_type is not None:
            events = [event for event in events if event.aggregate_type == aggregate_type]
        if aggregate_id is not None:
            events = [event for event in events if event.aggregate_id == aggregate_id]
        if event_type is not None:
            events = [event for event in events if event.event_type == event_type]
        if source is not None:
            events = [event for event in events if event.source == source]

        reverse = sort != "oldest_first"
        events.sort(key=lambda event: event.event_id)
        events.sort(key=lambda event: event_sort_key(event.occurred_at), reverse=reverse)
        safe_offset = max(offset, 0)
        safe_limit = max(limit, 0)
        return events[safe_offset : safe_offset + safe_limit]

    @staticmethod
    def _deduplicate(events: list[DomainEvent]) -> list[DomainEvent]:
        seen: set[str] = set()
        result: list[DomainEvent] = []
        for event in events:
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            result.append(event)
        return result
