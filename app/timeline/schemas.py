"""Timeline schemas used by builders, services and routes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from app.domain.events.time import normalize_event_datetime

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class ProductHistoryEvent:
    """Unified user-facing event for the product timeline."""

    event_id: str
    product_id: int
    event_type: str
    event_type_label: str
    event_group: str
    event_group_label: str
    source: str
    source_label: str
    occurred_at: datetime
    status: str
    status_label: str
    field: str | None = None
    field_label: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    comment: str | None = None
    confidence: float | None = None
    actor_id: str | None = None
    actor_label: str | None = None
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    related_id: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["occurred_at"] = normalize_event_datetime(self.occurred_at).isoformat()
        return payload


@dataclass(frozen=True)
class TimelinePagination:
    limit: int = 50
    offset: int = 0
    sort: str = "newest_first"


@dataclass(frozen=True)
class TimelineFilter:
    event_type: str = "all"
    source: str = "all"
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True)
class TimelinePageInfo:
    limit: int
    offset: int
    next_offset: int | None
    total_returned: int
    has_more: bool
    sort: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductTimeline:
    product_id: int
    items: list[ProductHistoryEvent]
    pagination: TimelinePageInfo
    warnings: list[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "items": [item.to_dict() for item in self.items],
            "pagination": self.pagination.to_dict(),
            "warnings": self.warnings,
        }
