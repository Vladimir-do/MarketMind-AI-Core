"""CSV file importer for the Universal Import Layer."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.importers.base import DEFAULT_FIELD_MAPPING, BaseImporter


class CsvImporter(BaseImporter):
    """Import products from a CSV file."""

    @classmethod
    def can_handle(cls, source: str | Path) -> bool:
        return Path(source).suffix.lower() == ".csv"

    def validate(self, source: str | Path) -> list[str]:
        p = Path(source)
        if not p.exists():
            return [f"File not found: {p}"]
        if not p.is_file():
            return [f"Not a file: {p}"]
        return []

    def extract(self, source: str | Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with open(source, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(dict(row))
        return rows

    def field_mapping(self) -> dict[str, str]:
        return DEFAULT_FIELD_MAPPING
