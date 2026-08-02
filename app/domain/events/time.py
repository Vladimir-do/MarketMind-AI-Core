"""Time helpers for domain and timeline events."""

from __future__ import annotations

from datetime import UTC, datetime


def normalize_event_datetime(value: datetime) -> datetime:
    """Return an UTC-aware datetime for event ordering and serialization.

    Legacy SQLite rows may contain naive datetimes. MarketMind treats those
    values as UTC because all current writers use UTC timestamps.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_legacy_utc_naive(value: datetime) -> datetime:
    """Convert a filter timestamp to the legacy SQLite DateTime shape.

    The conversion first preserves the instant by normalizing to UTC, then
    removes tzinfo only for comparison with existing SQLite rows.
    """
    return normalize_event_datetime(value).replace(tzinfo=None)


def event_sort_key(value: datetime) -> datetime:
    """Stable event sort key."""
    return normalize_event_datetime(value)
