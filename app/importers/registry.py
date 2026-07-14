"""Importer registry — routes files and strings to the correct importer."""

from __future__ import annotations

from pathlib import Path

from app.importers.base import ImportResult, ImportRowError
from app.importers.csv_importer import CsvImporter
from app.importers.excel_importer import ExcelImporter

IMPORTERS: list[type] = [CsvImporter, ExcelImporter]


def import_file(path: str | Path) -> ImportResult:
    """Route a file path to the appropriate importer and run it."""
    p = Path(path)
    for cls in IMPORTERS:
        if cls.can_handle(p):
            return cls().import_data(p)
    return ImportResult(errors=[ImportRowError(row_index=-1, message=f"No importer found for: {p.suffix}")])


def import_string(content: str, filename: str, source_type: str = "manual") -> ImportResult:
    """Import from an in-memory string (e.g. pasted from Telegram)."""
    p = Path(filename)
    if not p.suffix:
        p = p.with_suffix(".csv")

    tmp_path = Path(f"/tmp/_mim_import_{p.name}")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        result = import_file(tmp_path)
        result.metadata["source_type"] = source_type
        return result
    except Exception as exc:
        return ImportResult(errors=[ImportRowError(row_index=-1, message=str(exc))])
    finally:
        tmp_path.unlink(missing_ok=True)
