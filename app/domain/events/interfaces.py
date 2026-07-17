"""Protocol interfaces for Domain Events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.domain.events.models import DomainEvent


class EventBuilder(Protocol):
    """Converts source objects or actions into domain events."""

    def build(self, source: object) -> list[DomainEvent]:
        ...


class EventRepository(Protocol):
    """Storage interface for future persisted domain events."""

    async def append(self, event: DomainEvent) -> None:
        ...

    async def append_many(self, events: list[DomainEvent]) -> None:
        ...

    async def list_by_aggregate(
        self,
        aggregate_type: str,
        aggregate_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[DomainEvent]:
        ...


class EventSerializer(Protocol):
    """Stable serialization interface for events."""

    def dumps(self, event: DomainEvent) -> str:
        ...

    def loads(self, raw: str) -> DomainEvent:
        ...


class EventPublisher(Protocol):
    """Publishes events to in-process or future async consumers."""

    async def publish(self, event: DomainEvent) -> None:
        ...

    async def publish_many(self, events: list[DomainEvent]) -> None:
        ...


class EventReader(Protocol):
    """Reads event streams for consumers such as Timeline and Versioning."""

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
        ...
