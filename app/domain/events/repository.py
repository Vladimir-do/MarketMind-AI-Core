"""Persisted DomainEvent repository."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from app.database import DomainEventRecord
from app.domain.events.models import DomainEvent, EventActor
from app.domain.events.serializer import JsonEventSerializer
from app.domain.events.time import normalize_event_datetime, to_legacy_utc_naive

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_MAX_EVENT_JSON_BYTES = 64 * 1024


class DomainEventRepository:
    """Stores new non-reconstructable DomainEvents."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._serializer = JsonEventSerializer()

    async def append(
        self,
        event: DomainEvent,
        *,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> DomainEventRecord:
        raw = self._serializer.dumps(event)
        if len(raw.encode("utf-8")) > _MAX_EVENT_JSON_BYTES:
            raise ValueError("Domain event payload is too large")
        payload_json = json.dumps(event.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        metadata_json = json.dumps(event.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record = DomainEventRecord(
            event_id=event.event_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            source=event.source,
            actor_type=event.actor.actor_type if event.actor else "system",
            actor_id=event.actor.actor_id if event.actor else None,
            occurred_at=to_legacy_utc_naive(event.occurred_at),
            payload_json=payload_json,
            metadata_json=metadata_json,
            schema_version=event.version,
            correlation_id=correlation_id,
            causation_id=causation_id,
            created_at=to_legacy_utc_naive(normalize_event_datetime(event.occurred_at)),
        )
        self._session.add(record)
        return record

    async def list_by_aggregate(
        self,
        aggregate_type: str,
        aggregate_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[DomainEvent]:
        result = await self._session.execute(
            select(DomainEventRecord)
            .where(DomainEventRecord.aggregate_type == aggregate_type)
            .where(DomainEventRecord.aggregate_id == aggregate_id)
            .order_by(desc(DomainEventRecord.occurred_at), desc(DomainEventRecord.event_id))
            .limit(limit)
            .offset(offset)
        )
        return [self._to_event(record) for record in result.scalars().all()]

    @staticmethod
    def _to_event(record: DomainEventRecord) -> DomainEvent:
        payload = json.loads(record.payload_json or "{}")
        metadata = json.loads(record.metadata_json or "{}")
        actor = EventActor(record.actor_type, actor_id=record.actor_id)
        return DomainEvent(
            event_id=record.event_id,
            aggregate_type=record.aggregate_type,
            aggregate_id=record.aggregate_id,
            event_type=record.event_type,
            source=record.source,
            actor=actor,
            occurred_at=record.occurred_at,
            payload=payload,
            metadata=metadata,
            version=record.schema_version,
        )
