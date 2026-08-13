"""Excel (.xlsx/.xlsm) file importer for the Universal Import Layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from app.importers.base import DEFAULT_FIELD_MAPPING, BaseImporter


class ExcelImporter(BaseImporter):
    """Import products from an Excel workbook."""

    @classmethod
    def can_handle(cls, source: str | Path) -> bool:
        return Path(source).suffix.lower() in (".xlsx", ".xlsm")

    def validate(self, source: str | Path) -> list[str]:
        p = Path(source)
        if not p.exists():
            return [f"File not found: {p}"]
        if not p.is_file():
            return [f"Not a file: {p}"]
        return []

    def extract(self, source: str | Path) -> list[dict[str, Any]]:
        wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
        ws = wb.active
        if ws is None or ws.max_row is None or ws.max_row < 2:
            wb.close()
            return []

        rows_iter = ws.iter_rows(values_only=True)
        header_raw = next(rows_iter, None)
        if not header_raw:
            wb.close()
            return []

        headers = [str(h).strip().lower() if h is not None else f"col_{i}" for i, h in enumerate(header_raw)]

        rows: list[dict[str, Any]] = []
        for row in rows_iter:
            if row is None:
                continue
            row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row))) if i < len(row) and row[i] is not None}
            if any(v is not None for v in row_dict.values()):
                rows.append(row_dict)

        wb.close()
        return rows

    def field_mapping(self) -> dict[str, str]:
        return DEFAULT_FIELD_MAPPING
