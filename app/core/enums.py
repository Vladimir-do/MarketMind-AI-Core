from __future__ import annotations

from enum import StrEnum


class Marketplace(StrEnum):
    OZON = "ozon"
    WILDBERRIES = "wildberries"
    ALIEXPRESS = "aliexpress"
    UNKNOWN = "unknown"


class AvailabilityStatus(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class FetchStatus(StrEnum):
    OK = "ok"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"

