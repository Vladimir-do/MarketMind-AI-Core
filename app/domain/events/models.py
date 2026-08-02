"""Core Domain Event model.

Domain events are machine-readable facts. UI labels and presentation-specific
fields belong to timeline/read models, not to this contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.domain.events.time import normalize_event_datetime

if TYPE_CHECKING:
    from datetime import datetime


class AggregateType(StrEnum):
    PRODUCT = "product"
    APPROVAL = "approval"
    PARSER_ATTEMPT = "parser_attempt"
    JOB = "job"
    USER = "user"
    SYSTEM = "system"


class EventSource(StrEnum):
    IMPORT = "import"
    PARSER = "parser"
    SYNC = "sync"
    AI = "ai"
    USER = "user"
    SYSTEM = "system"
    WORKER = "worker"
    API = "api"
    BACKFILL = "backfill"


class ActorType(StrEnum):
    USER = "user"
    AI = "ai"
    WORKER = "worker"
    SYSTEM = "system"
    PARSER = "parser"


@dataclass(frozen=True)
class EventActor:
    """Actor that initiated a domain event."""

    actor_type: str
    actor_id: str | None = None
    display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DomainEvent:
    """Stable domain-level fact used by timeline, versioning and audit layers."""

    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    source: str
    occurred_at: datetime
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    actor: EventActor | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.aggregate_type:
            raise ValueError("aggregate_type is required")
        if not self.aggregate_id:
            raise ValueError("aggregate_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.source:
            raise ValueError("source is required")
        if self.version < 1:
            raise ValueError("version must be positive")
        object.__setattr__(self, "occurred_at", normalize_event_datetime(self.occurred_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "source": self.source,
            "actor": self.actor.to_dict() if self.actor else None,
            "occurred_at": normalize_event_datetime(self.occurred_at).isoformat(),
            "payload": self.payload,
            "metadata": self.metadata,
            "version": self.version,
        }
