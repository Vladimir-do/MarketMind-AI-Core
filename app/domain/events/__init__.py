"""Domain Events platform contracts."""

from app.domain.events.builders import ApprovalEventBuilder, ProductEventBuilder
from app.domain.events.interfaces import (
    EventBuilder,
    EventPublisher,
    EventReader,
    EventRepository,
    EventSerializer,
)
from app.domain.events.models import DomainEvent, EventActor
from app.domain.events.reader import ReadModelEventReader
from app.domain.events.serializer import JsonEventSerializer

__all__ = [
    "ApprovalEventBuilder",
    "DomainEvent",
    "EventActor",
    "EventBuilder",
    "EventPublisher",
    "EventReader",
    "EventRepository",
    "EventSerializer",
    "JsonEventSerializer",
    "ProductEventBuilder",
    "ReadModelEventReader",
]
