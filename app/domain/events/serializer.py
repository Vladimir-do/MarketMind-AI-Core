"""JSON serialization for Domain Events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.domain.events.models import DomainEvent, EventActor

_SENSITIVE_KEYWORDS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "jwt",
    "password",
    "private_key",
    "secret",
    "token",
)


class JsonEventSerializer:
    """Serialize DomainEvent instances to deterministic JSON."""

    def dumps(self, event: DomainEvent) -> str:
        payload = event.to_dict()
        self._ensure_no_sensitive_keys(payload)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def loads(self, raw: str) -> DomainEvent:
        data = json.loads(raw)
        self._ensure_no_sensitive_keys(data)
        actor_data = data.get("actor")
        actor = EventActor(**actor_data) if actor_data else None
        return DomainEvent(
            event_id=data["event_id"],
            aggregate_type=data["aggregate_type"],
            aggregate_id=data["aggregate_id"],
            event_type=data["event_type"],
            source=data["source"],
            actor=actor,
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            payload=data.get("payload") or {},
            metadata=data.get("metadata") or {},
            version=int(data.get("version") or 1),
        )

    def _ensure_no_sensitive_keys(self, value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if any(marker in key_text for marker in _SENSITIVE_KEYWORDS):
                    location = f"{path}.{key}" if path else str(key)
                    raise ValueError(f"Sensitive key is not allowed in domain event: {location}")
                self._ensure_no_sensitive_keys(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._ensure_no_sensitive_keys(item, f"{path}[{index}]")
