"""Base importer and shared result types for the Universal Import Layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.importers.image_fetcher import resolve_image_url_from_source
from app.products.schema import UnifiedProduct

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_FIELD_MAPPING: dict[str, str] = {
    # Russian names
    "название": "name",
    "товар": "name",
    "наименование": "name",
    "имя": "name",
    "бренд": "brand",
    "цена": "price",
    "старая цена": "old_price",
    "скидка": "discount_pct",
    "описание": "description",
    "категория": "category",
    "артикул": "sku",
    "sku": "sku",
    "вес": "weight_g",
    "ширина": "width_mm",
    "высота": "height_mm",
    "глубина": "depth_mm",
    "фото": "image_urls",
    "изображение": "image_urls",
    "изображения": "image_urls",
    "-url": "source_url",
    "ссылка": "source_url",
    "маркетплейс": "marketplace",
    "валюта": "currency",
    # English names
    "name": "name",
    "title": "name",
    "product": "name",
    "brand": "brand",
    "price": "price",
    "old_price": "old_price",
    "discount": "discount_pct",
    "description": "description",
    "category": "category",
    "weight": "weight_g",
    "width": "width_mm",
    "height": "height_mm",
    "depth": "depth_mm",
    "image": "image_urls",
    "images": "image_urls",
    "url": "source_url",
    "source_url": "source_url",
    "marketplace": "marketplace",
    "currency": "currency",
}


@dataclass
class ImportRowError:
    """Records a single row-level parsing error during import."""

    row_index: int
    message: str
    raw_value: Any = None


@dataclass
class ImportResult:
    """Aggregated outcome of an import operation."""

    products: list[UnifiedProduct] = field(default_factory=list)
    errors: list[ImportRowError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseImporter(ABC):
    """Abstract base for file-based importers (CSV, Excel, etc.)."""

    @classmethod
    @abstractmethod
    def can_handle(cls, source: str | Path) -> bool:
        """Return True if this importer can process the given source."""
        ...

    @abstractmethod
    def validate(self, source: str | Path) -> list[str]:
        """Validate the source and return a list of error messages (empty = OK)."""
        ...

    @abstractmethod
    def extract(self, source: str | Path) -> list[dict[str, Any]]:
        """Read raw rows from the source as dicts."""
        ...

    @abstractmethod
    def field_mapping(self) -> dict[str, str]:
        """Return a mapping from source column names to UnifiedProduct field names."""
        ...

    def normalize(self, rows: list[dict[str, Any]]) -> tuple[list[UnifiedProduct], list[ImportRowError]]:
        """Map raw rows to UnifiedProduct instances using field_mapping().

        Returns a tuple of (products, errors) so callers can inspect failures.
        """
        mapping = self.field_mapping()
        products: list[UnifiedProduct] = []
        errors: list[ImportRowError] = []
        for idx, row in enumerate(rows):
            try:
                product = self._map_row(row, mapping, row_index=idx)
                if product.name:
                    products.append(product)
            except Exception as exc:
                errors.append(ImportRowError(row_index=idx, message=str(exc), raw_value=row))
        return products, errors

    def import_data(self, source: str | Path) -> ImportResult:
        """Full pipeline: validate → extract → normalize."""
        errors_msg = self.validate(source)
        if errors_msg:
            return ImportResult(errors=[ImportRowError(row_index=-1, message=m) for m in errors_msg])

        try:
            rows = self.extract(source)
        except Exception as exc:
            return ImportResult(errors=[ImportRowError(row_index=-1, message=str(exc))])

        products, normalize_errors = self.normalize(rows)
        return ImportResult(
            products=products,
            errors=normalize_errors,
            metadata={"source": str(source), "rows_extracted": len(rows), "rows_normalized": len(products)},
        )

    def _map_row(
        self,
        row: dict[str, Any],
        mapping: dict[str, str],
        row_index: int = 0,
    ) -> UnifiedProduct:
        """Convert a single raw row dict to UnifiedProduct using the field mapping."""
        fields: dict[str, Any] = {}
        for src_col, target_field in mapping.items():
            val = row.get(src_col)
            if val is None:
                continue
            val_str = str(val).strip()
            if not val_str:
                continue
            if target_field in ("price", "old_price", "discount_pct", "weight_g", "width_mm", "height_mm", "depth_mm"):
                try:
                    fields[target_field] = int(float(val_str))
                except (ValueError, TypeError):
                    continue
            elif target_field == "image_urls":
                fields[target_field] = [u.strip() for u in val_str.split(",") if u.strip()]
            elif target_field == "tags":
                fields[target_field] = [t.strip() for t in val_str.split(",") if t.strip()]
            else:
                fields[target_field] = val_str

        image_urls = list(fields.get("image_urls") or [])
        thumbnail_url = image_urls[0] if image_urls else None
        if not image_urls:
            resolved_image_url = resolve_image_url_from_source(fields.get("source_url"))
            if resolved_image_url:
                image_urls = [resolved_image_url]
                thumbnail_url = resolved_image_url

        return UnifiedProduct(
            name=fields.get("name", ""),
            source_id=fields.get("sku", fields.get("source_id", f"row_{row_index}")),
            source_type="file_import",
            raw=dict(row),
            image_urls=image_urls,
            thumbnail_url=thumbnail_url,
            **{k: v for k, v in fields.items() if k not in ("name", "source_id", "image_urls")},
        )
