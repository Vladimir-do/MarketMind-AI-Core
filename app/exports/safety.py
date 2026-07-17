"""Spreadsheet and filename safety helpers."""

from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_spreadsheet_cell(value: Any) -> Any:
    """Return a safe value for CSV/XLSX cells without losing readable text."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def sanitize_export_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: sanitize_spreadsheet_cell(value) for key, value in row.items()}
