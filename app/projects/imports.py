"""Safe project file preview and mapped import helpers."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

from app.config import IMPORT_MAX_CELL_CHARS, IMPORT_MAX_FILE_BYTES, IMPORT_MAX_ROWS, IMPORT_PREVIEW_ROWS
from app.importers.base import DEFAULT_FIELD_MAPPING
from app.products.schema import UnifiedProduct

CANONICAL_FIELDS = {
    "marketplace",
    "sku",
    "vendor_code",
    "barcode",
    "title",
    "description",
    "brand",
    "category",
    "price",
    "old_price",
    "cost",
    "availability",
    "attributes",
    "source_url",
    "image_urls",
    "skip",
}

FIELD_ALIASES = {
    **DEFAULT_FIELD_MAPPING,
    "название": "title",
    "наименование": "title",
    "товар": "title",
    "артикул": "sku",
    "штрихкод": "barcode",
    "баркод": "barcode",
    "остаток": "availability",
    "наличие": "availability",
    "себестоимость": "cost",
    "закупка": "cost",
    "url": "source_url",
    "ссылка": "source_url",
    "картинка": "image_urls",
    "фото": "image_urls",
}


@dataclass(frozen=True)
class ImportCellError:
    row_number: int
    column: str | None
    code: str
    value_preview: str
    message: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportPreview:
    source_path: str
    original_filename: str
    file_format: str
    size_bytes: int
    sha256: str
    encoding: str | None = None
    delimiter: str | None = None
    sheets: list[str] = field(default_factory=list)
    hidden_sheets: list[str] = field(default_factory=list)
    selected_sheet: str | None = None
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    preview_rows: list[dict[str, Any]] = field(default_factory=list)
    suggested_mapping: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[ImportCellError] = field(default_factory=list)
    duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = [error.to_dict() for error in self.errors]
        return data


def analyze_import_file(
    *,
    path: Path,
    original_filename: str,
    sha256: str,
    size_bytes: int,
    file_format: str,
    duplicate: bool = False,
    selected_sheet: str | None = None,
) -> ImportPreview:
    _validate_size(size_bytes)
    suffix = Path(original_filename).suffix.lower()
    if suffix.removeprefix(".") != file_format:
        raise ValueError("Расширение файла не совпадает с сохранённым форматом")
    if file_format == "csv":
        return _analyze_csv(path, original_filename, sha256, size_bytes, duplicate=duplicate)
    if file_format in {"xlsx", "xlsm"}:
        return _analyze_excel(
            path,
            original_filename,
            sha256,
            size_bytes,
            file_format=file_format,
            duplicate=duplicate,
            selected_sheet=selected_sheet,
        )
    raise ValueError("Формат файла не поддерживается")


def build_products_from_preview(
    preview: ImportPreview,
    *,
    mapping: dict[str, str] | None = None,
) -> tuple[list[UnifiedProduct], list[ImportCellError]]:
    effective_mapping = _normalize_mapping(mapping or preview.suggested_mapping, preview.columns)
    products: list[UnifiedProduct] = []
    errors: list[ImportCellError] = []
    rows = _read_rows_for_preview(preview)
    for index, row in enumerate(rows[:IMPORT_MAX_ROWS], start=2):
        product, row_errors = _row_to_product(row, effective_mapping, index)
        errors.extend(row_errors)
        if product is not None:
            products.append(product)
    return products, errors


def _read_rows_for_preview(preview: ImportPreview) -> list[dict[str, Any]]:
    path = Path(preview.source_path)
    if preview.file_format == "csv":
        text = path.read_text(encoding=preview.encoding or "utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), delimiter=preview.delimiter or ",")
        return [dict(row) for row in reader]
    return _excel_rows(path, preview.selected_sheet)


def _analyze_csv(
    path: Path,
    original_filename: str,
    sha256: str,
    size_bytes: int,
    *,
    duplicate: bool,
) -> ImportPreview:
    raw = path.read_bytes()
    if raw.startswith(b"PK\x03\x04"):
        raise ValueError("Файл похож на Excel/ZIP, но имеет расширение CSV")
    text = raw.decode("utf-8-sig")
    delimiter, delimiter_warning = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = [str(column or "").strip() for column in (reader.fieldnames or [])]
    rows = [dict(row) for row in reader]
    errors = _validate_rows(rows)
    warnings = []
    if delimiter_warning:
        warnings.append(delimiter_warning)
    if duplicate:
        warnings.append("Этот файл уже импортировался в проект.")
    return ImportPreview(
        source_path=path.as_posix(),
        original_filename=original_filename,
        file_format="csv",
        size_bytes=size_bytes,
        sha256=sha256,
        encoding="utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
        delimiter=delimiter,
        row_count=len(rows),
        columns=columns,
        preview_rows=rows[:IMPORT_PREVIEW_ROWS],
        suggested_mapping=guess_mapping(columns),
        warnings=warnings,
        errors=errors,
        duplicate=duplicate,
    )


def _analyze_excel(
    path: Path,
    original_filename: str,
    sha256: str,
    size_bytes: int,
    *,
    file_format: str,
    duplicate: bool,
    selected_sheet: str | None,
) -> ImportPreview:
    if not zipfile.is_zipfile(path):
        raise ValueError("Файл не похож на корректный XLSX/XLSM")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = workbook.sheetnames
        hidden_sheets = [sheet.title for sheet in workbook.worksheets if sheet.sheet_state != "visible"]
        sheet_name = selected_sheet or workbook.active.title
        if sheet_name not in sheets:
            raise ValueError("Выбранный лист не найден в книге")
        rows = _excel_rows(path, sheet_name)
        columns = list(rows[0].keys()) if rows else []
        warnings = []
        if hidden_sheets:
            warnings.append("В книге есть скрытые листы: " + ", ".join(hidden_sheets))
        if len(sheets) > 1 and selected_sheet is None:
            warnings.append("В книге несколько листов. Проверьте, что выбран нужный лист.")
        if duplicate:
            warnings.append("Этот файл уже импортировался в проект.")
        return ImportPreview(
            source_path=path.as_posix(),
            original_filename=original_filename,
            file_format=file_format,
            size_bytes=size_bytes,
            sha256=sha256,
            sheets=sheets,
            hidden_sheets=hidden_sheets,
            selected_sheet=sheet_name,
            row_count=len(rows),
            columns=columns,
            preview_rows=rows[:IMPORT_PREVIEW_ROWS],
            suggested_mapping=guess_mapping(columns),
            warnings=warnings,
            errors=_validate_rows(rows),
            duplicate=duplicate,
        )
    finally:
        workbook.close()


def _excel_rows(path: Path, selected_sheet: str | None) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[selected_sheet] if selected_sheet else workbook.active
        rows_iter = worksheet.iter_rows(values_only=True)
        header_raw = next(rows_iter, None)
        if not header_raw:
            return []
        headers = [str(value).strip() if value is not None else f"col_{index}" for index, value in enumerate(header_raw)]
        rows: list[dict[str, Any]] = []
        for row in rows_iter:
            row_dict = {
                headers[index]: row[index]
                for index in range(min(len(headers), len(row)))
                if index < len(row) and row[index] is not None
            }
            if any(value not in (None, "") for value in row_dict.values()):
                rows.append(row_dict)
        return rows
    finally:
        workbook.close()


def guess_mapping(columns: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for column in columns:
        normalized = _normalize_header(column)
        result[column] = FIELD_ALIASES.get(normalized, "attributes")
    return result


def _normalize_mapping(mapping: dict[str, str], columns: list[str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for column in columns:
        target = str(mapping.get(column) or "attributes").strip()
        if target.startswith("attribute:") or target in CANONICAL_FIELDS:
            normalized[column] = target
        else:
            normalized[column] = "attributes"
    return normalized


def _row_to_product(
    row: dict[str, Any],
    mapping: dict[str, str],
    row_number: int,
) -> tuple[UnifiedProduct | None, list[ImportCellError]]:
    fields: dict[str, Any] = {}
    attributes: dict[str, str] = {}
    errors: list[ImportCellError] = []
    for column, value in row.items():
        target = mapping.get(column, "attributes")
        if target == "skip":
            continue
        if value is None or str(value).strip() == "":
            continue
        text = str(value).strip()
        if len(text) > IMPORT_MAX_CELL_CHARS:
            errors.append(_error(row_number, column, "cell_too_large", text, "Слишком длинное значение", "Сократите значение в ячейке."))
            continue
        if target.startswith("attribute:"):
            attributes[target.partition(":")[2] or column] = text
        elif target == "attributes":
            attributes[column] = text
        elif target in {"price", "old_price", "cost"}:
            parsed = _parse_int(text)
            if parsed is None:
                errors.append(_error(row_number, column, "invalid_number", text, "Ожидалось числовое значение", "Исправьте число или сопоставьте колонку как характеристику."))
            else:
                fields[target] = parsed
        elif target == "image_urls":
            fields[target] = [item.strip() for item in text.split(",") if item.strip()]
        elif target == "title":
            fields["name"] = text
        else:
            fields[target] = text
    title = str(fields.get("name") or "").strip()
    sku = str(fields.get("sku") or fields.get("vendor_code") or "").strip()
    if not title:
        errors.append(_error(row_number, "title", "missing_title", "", "Не найдено название товара", "Сопоставьте колонку с названием или заполните значение."))
        return None, errors
    product = UnifiedProduct(
        name=title,
        source_id=sku or f"row_{row_number}",
        source_type="project_file_import",
        description=fields.get("description"),
        brand=fields.get("brand"),
        category=fields.get("category"),
        sku=sku or None,
        price=fields.get("price"),
        old_price=fields.get("old_price"),
        image_urls=list(fields.get("image_urls") or []),
        attributes={key: str(value) for key, value in attributes.items()},
        source_url=fields.get("source_url"),
        marketplace=fields.get("marketplace"),
        availability=str(fields.get("availability") or "in_stock"),
        raw=dict(row),
    )
    return product, errors


def _detect_delimiter(text: str) -> tuple[str, str | None]:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        delimiter = dialect.delimiter
    except csv.Error:
        comma = sample.count(",")
        semicolon = sample.count(";")
        delimiter = ";" if semicolon > comma else ","
        return delimiter, "Разделитель CSV определён неуверенно. Проверьте preview перед импортом."
    return delimiter, None


def _validate_size(size_bytes: int) -> None:
    if size_bytes > IMPORT_MAX_FILE_BYTES:
        raise ValueError("Файл слишком большой для безопасного импорта")


def _validate_rows(rows: list[dict[str, Any]]) -> list[ImportCellError]:
    errors: list[ImportCellError] = []
    if len(rows) > IMPORT_MAX_ROWS:
        errors.append(_error(0, None, "too_many_rows", str(len(rows)), "В файле слишком много строк", "Разделите файл на несколько импортов."))
    for row_index, row in enumerate(rows[:IMPORT_MAX_ROWS], start=2):
        for column, value in row.items():
            text = "" if value is None else str(value)
            if len(text) > IMPORT_MAX_CELL_CHARS:
                errors.append(_error(row_index, column, "cell_too_large", text, "Слишком длинное значение", "Сократите значение в ячейке."))
    return errors


def _parse_int(value: str) -> int | None:
    try:
        return int(float(value.replace(" ", "").replace(",", ".")))
    except ValueError:
        return None


def _normalize_header(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _error(
    row_number: int,
    column: str | None,
    code: str,
    value: str,
    message: str,
    recommendation: str,
) -> ImportCellError:
    preview = value[:120]
    return ImportCellError(
        row_number=row_number,
        column=column,
        code=code,
        value_preview=preview,
        message=message,
        recommendation=recommendation,
    )
