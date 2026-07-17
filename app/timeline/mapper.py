"""Map machine-readable DomainEvents to user-facing ProductHistoryEvents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.events.time import normalize_event_datetime
from app.timeline.enums import (
    EVENT_GROUP_LABELS,
    EVENT_TYPE_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    TimelineEventGroup,
    TimelineEventType,
    TimelineSource,
    TimelineStatus,
)
from app.timeline.schemas import ProductHistoryEvent

if TYPE_CHECKING:
    from app.domain.events.models import DomainEvent


_FIELD_LABELS = {
    "product": "Карточка товара",
    "price": "Цена",
    "availability_status": "Наличие",
    "name": "Название",
    "title": "Название",
    "description": "Описание",
}


class TimelineEventMapper:
    """Converts DomainEvent instances into timeline presentation events."""

    def to_history_event(self, event: DomainEvent) -> ProductHistoryEvent | None:
        mapping = {
            "product.imported": self._product_imported,
            "product.price_changed": self._price_changed,
            "product.stock_changed": self._stock_changed,
            "ai.suggestion_created": self._ai_suggestion_created,
            "approval.approved": self._approval_approved,
            "approval.rejected": self._approval_rejected,
            "approval.applied": self._approval_applied,
            "approval.rolled_back": self._approval_rolled_back,
        }
        handler = mapping.get(event.event_type)
        if handler is None:
            return None
        return handler(event)

    def to_history_events(self, events: list[DomainEvent]) -> list[ProductHistoryEvent]:
        result: list[ProductHistoryEvent] = []
        for event in events:
            mapped = self.to_history_event(event)
            if mapped is not None:
                result.append(mapped)
        return result

    def _product_imported(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._event(
            event,
            event_id=f"product:{event.aggregate_id}:import",
            product_id=int(event.aggregate_id),
            event_type=TimelineEventType.PRODUCT_IMPORTED,
            event_group=TimelineEventGroup.IMPORT,
            source=TimelineSource.IMPORT,
            field="product",
            old_value=None,
            new_value=self._first_text(event.payload.get("name"), event.payload.get("url")),
            status=TimelineStatus.RECORDED,
            reason="Товар впервые сохранён в каталоге",
        )

    def _price_changed(self, event: DomainEvent) -> ProductHistoryEvent:
        price_history_id = self._required_payload(event, "price_history_id")
        return self._event(
            event,
            event_id=f"price:{price_history_id}:price",
            product_id=int(event.aggregate_id),
            event_type=TimelineEventType.PRICE_CHANGED,
            event_group=TimelineEventGroup.PRICE,
            source=TimelineSource.SYNC,
            field="price",
            old_value=self._price_value(event.payload.get("old_value")),
            new_value=self._price_value(event.payload.get("new_value")),
            status=TimelineStatus.RECORDED,
            reason="Изменилась цена товара",
            related_entity_type="price_history",
            related_entity_id=str(price_history_id),
        )

    def _stock_changed(self, event: DomainEvent) -> ProductHistoryEvent:
        price_history_id = self._required_payload(event, "price_history_id")
        return self._event(
            event,
            event_id=f"price:{price_history_id}:stock",
            product_id=int(event.aggregate_id),
            event_type=TimelineEventType.STOCK_CHANGED,
            event_group=TimelineEventGroup.STOCK,
            source=TimelineSource.SYNC,
            field="availability_status",
            old_value=self._empty_dash(event.payload.get("old_value")),
            new_value=self._empty_dash(event.payload.get("new_value")),
            status=TimelineStatus.RECORDED,
            reason="Изменился статус наличия товара",
            related_entity_type="price_history",
            related_entity_id=str(price_history_id),
        )

    def _ai_suggestion_created(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._approval_event(
            event,
            suffix="created",
            event_type=TimelineEventType.AI_SUGGESTION_CREATED,
            event_group=TimelineEventGroup.AI,
            source=TimelineSource.AI,
            status=TimelineStatus.PENDING,
            reason=event.payload.get("reason"),
        )

    def _approval_approved(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._approval_event(
            event,
            suffix="approved",
            event_type=TimelineEventType.AI_SUGGESTION_APPROVED,
            event_group=TimelineEventGroup.DECISION,
            source=TimelineSource.USER,
            status=TimelineStatus.APPROVED,
            reason=event.payload.get("reason"),
        )

    def _approval_rejected(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._approval_event(
            event,
            suffix="rejected",
            event_type=TimelineEventType.AI_SUGGESTION_REJECTED,
            event_group=TimelineEventGroup.DECISION,
            source=TimelineSource.USER,
            status=TimelineStatus.REJECTED,
            reason=event.payload.get("reason"),
        )

    def _approval_applied(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._approval_event(
            event,
            suffix="applied",
            event_type=TimelineEventType.AI_SUGGESTION_APPLIED,
            event_group=TimelineEventGroup.DECISION,
            source=TimelineSource.USER,
            status=TimelineStatus.APPLIED,
            reason="Одобренное предложение применено к товару",
        )

    def _approval_rolled_back(self, event: DomainEvent) -> ProductHistoryEvent:
        return self._approval_event(
            event,
            suffix="rolled_back",
            event_type=TimelineEventType.AI_SUGGESTION_ROLLED_BACK,
            event_group=TimelineEventGroup.DECISION,
            source=TimelineSource.USER,
            status=TimelineStatus.ROLLED_BACK,
            reason="Пользователь отменил ранее принятое решение",
        )

    def _approval_event(
        self,
        event: DomainEvent,
        *,
        suffix: str,
        event_type: TimelineEventType,
        event_group: TimelineEventGroup,
        source: TimelineSource,
        status: TimelineStatus,
        reason: str | None,
    ) -> ProductHistoryEvent:
        approval_id = str(event.metadata.get("approval_id") or event.aggregate_id)
        return self._event(
            event,
            event_id=f"approval:{approval_id}:{suffix}",
            product_id=int(event.payload["product_id"]),
            event_type=event_type,
            event_group=event_group,
            source=source,
            field=event.payload.get("field"),
            old_value=event.payload.get("old_value"),
            new_value=event.payload.get("new_value"),
            status=status,
            reason=reason,
            confidence=event.payload.get("confidence"),
            related_entity_type="approval",
            related_entity_id=approval_id,
        )

    @staticmethod
    def _event(
        event: DomainEvent,
        *,
        event_id: str,
        product_id: int,
        event_type: TimelineEventType,
        event_group: TimelineEventGroup,
        source: TimelineSource,
        field: str | None,
        old_value: str | None,
        new_value: str | None,
        status: TimelineStatus,
        reason: str | None,
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
            occurred_at=normalize_event_datetime(event.occurred_at),
            status=status.value,
            status_label=STATUS_LABELS.get(status, status.value),
            field=field,
            field_label=_FIELD_LABELS.get(field or "", field),
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            comment=None,
            confidence=confidence,
            actor_id=event.actor.actor_id if event.actor else None,
            actor_label=event.actor.display_name if event.actor else None,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            related_id=related_entity_id,
            metadata={"domain_event_id": event.event_id},
        )

    @staticmethod
    def _price_value(value: Any) -> str:
        return "—" if value is None else f"{value} ₽"

    @staticmethod
    def _empty_dash(value: Any) -> str:
        return str(value) if value else "—"

    @staticmethod
    def _first_text(*values: Any) -> str | None:
        for value in values:
            if value:
                return str(value)
        return None

    @staticmethod
    def _required_payload(event: DomainEvent, key: str) -> Any:
        value = event.payload.get(key)
        if value is None:
            raise ValueError(f"Domain event {event.event_id} is missing payload.{key}")
        return value
