"""Read-only product card versions derived from timeline events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from app.domain.events.time import event_sort_key, normalize_event_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from app.database import Product
    from app.timeline.schemas import ProductHistoryEvent


_VERSION_EVENT_TYPES = {
    "product_imported",
    "price_changed",
    "stock_changed",
    "ai_suggestion_applied",
    "ai_suggestion_rolled_back",
}

_FIELD_LABELS = {
    "product": "Карточка товара",
    "name": "Название",
    "title": "Название",
    "description": "Описание",
    "brand": "Бренд",
    "price": "Цена",
    "availability_status": "Наличие",
    "image_url": "Изображение",
    "quality_score": "Quality Score",
}

_VERSION_TYPE_LABELS = {
    "import": "Импорт",
    "price": "Цена",
    "stock": "Остатки",
    "ai_applied": "AI применено",
    "rollback": "Откат",
}

_ALL_VERSION_FIELDS = {
    "name",
    "description",
    "brand",
    "price",
    "availability",
    "image_url",
    "image_urls",
    "attributes",
    "ai_status",
    "quality_score",
}


@dataclass(frozen=True)
class ProductVersionChange:
    """Single field change between product versions."""

    field: str
    field_label: str
    old_value: str | None
    new_value: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductVersionSnapshot:
    """Best-effort product state after a version event."""

    name: str | None = None
    description: str | None = None
    brand: str | None = None
    price: str | None = None
    availability: str | None = None
    image_url: str | None = None
    image_urls: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    ai_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductVersion:
    """Read-only version of a product card."""

    version_id: str
    product_id: int
    version_number: int
    created_at: datetime
    created_by: str | None
    source: str
    version_type: str
    version_type_label: str
    title: str
    changes: list[ProductVersionChange]
    snapshot: ProductVersionSnapshot
    quality_score: int | None
    comment: str | None
    timeline_event_ids: list[str]
    is_derived: bool = True
    snapshot_completeness: str = "partial"
    known_fields: list[str] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    quality_score_is_historical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "product_id": self.product_id,
            "version_number": self.version_number,
            "created_at": normalize_event_datetime(self.created_at).isoformat(),
            "created_by": self.created_by,
            "source": self.source,
            "version_type": self.version_type,
            "version_type_label": self.version_type_label,
            "title": self.title,
            "changes": [change.to_dict() for change in self.changes],
            "snapshot": self.snapshot.to_dict(),
            "quality_score": self.quality_score,
            "comment": self.comment,
            "timeline_event_ids": self.timeline_event_ids,
            "is_derived": self.is_derived,
            "snapshot_completeness": self.snapshot_completeness,
            "known_fields": self.known_fields,
            "unknown_fields": self.unknown_fields,
            "source_event_ids": self.source_event_ids,
            "quality_score_is_historical": self.quality_score_is_historical,
        }


@dataclass(frozen=True)
class ProductVersionComparison:
    """Comparison between two product versions."""

    product_id: int
    from_version: int
    to_version: int
    changes: list[ProductVersionChange]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "changes": [change.to_dict() for change in self.changes],
            "warnings": self.warnings,
        }


class ProductVersionBuilder:
    """Build product versions from timeline events without persisting snapshots."""

    def build(
        self,
        *,
        product: Product,
        timeline_events: list[ProductHistoryEvent],
        quality_score: int | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "newest_first",
        version_type: str = "all",
    ) -> list[ProductVersion]:
        version_events = [
            event
            for event in timeline_events
            if event.event_type in _VERSION_EVENT_TYPES
        ]
        version_events.sort(key=lambda event: event_sort_key(event.occurred_at))

        versions: list[ProductVersion] = []
        snapshot_state = ProductVersionSnapshot(
            name=product.name,
            image_url=product.image_url,
            image_urls=[product.image_url] if product.image_url else [],
        )
        for index, event in enumerate(version_events, start=1):
            version_type_value = self._version_type_for_event(event)
            changes = self._changes_for_event(event)
            snapshot_state = self._apply_event_to_snapshot(snapshot_state, event)
            known_fields = self._known_fields(snapshot_state)
            unknown_fields = sorted(_ALL_VERSION_FIELDS - set(known_fields))
            versions.append(
                ProductVersion(
                    version_id=f"version:{product.id}:{index:04d}",
                    product_id=product.id,
                    version_number=index,
                    created_at=event.occurred_at,
                    created_by=None if event.source in {"ai", "sync", "import"} else event.source_label,
                    source=event.source_label,
                    version_type=version_type_value,
                    version_type_label=_VERSION_TYPE_LABELS.get(version_type_value, version_type_value),
                    title=event.event_type_label,
                    changes=changes,
                    snapshot=snapshot_state,
                    quality_score=quality_score,
                    comment=event.comment or event.reason,
                    timeline_event_ids=[event.event_id],
                    known_fields=known_fields,
                    unknown_fields=unknown_fields,
                    source_event_ids=[event.event_id],
                )
            )

        if version_type != "all":
            versions = [version for version in versions if version.version_type == version_type]

        if sort != "oldest_first":
            versions = list(reversed(versions))

        safe_offset = max(offset, 0)
        safe_limit = max(limit, 0)
        return versions[safe_offset : safe_offset + safe_limit]

    def get_version(self, versions: list[ProductVersion], version_number: int) -> ProductVersion | None:
        for version in versions:
            if version.version_number == version_number:
                return version
        return None

    def compare(
        self,
        *,
        product_id: int,
        from_version: ProductVersion,
        to_version: ProductVersion,
    ) -> ProductVersionComparison:
        changes: list[ProductVersionChange] = []
        from_snapshot = from_version.snapshot.to_dict()
        to_snapshot = to_version.snapshot.to_dict()
        for field_name in ("name", "description", "brand", "price", "availability", "image_url", "ai_status"):
            old = self._stringify_snapshot_value(from_snapshot.get(field_name))
            new = self._stringify_snapshot_value(to_snapshot.get(field_name))
            if old != new:
                changes.append(
                    ProductVersionChange(
                        field=field_name,
                        field_label=_FIELD_LABELS.get(field_name, field_name),
                        old_value=old,
                        new_value=new,
                    )
                )
        warnings = [
            "Описание, бренд, характеристики и полный набор изображений исторически не сохранялись полностью."
        ]
        return ProductVersionComparison(
            product_id=product_id,
            from_version=from_version.version_number,
            to_version=to_version.version_number,
            changes=changes,
            warnings=warnings,
        )

    def _apply_event_to_snapshot(
        self,
        snapshot: ProductVersionSnapshot,
        event: ProductHistoryEvent,
    ) -> ProductVersionSnapshot:
        data = snapshot.to_dict()
        field_name = event.field or ""
        if event.event_type == "product_imported":
            data["name"] = event.new_value or data.get("name")
        elif event.event_type == "price_changed":
            data["price"] = event.new_value
        elif event.event_type == "stock_changed":
            data["availability"] = event.new_value
        elif event.event_type in {"ai_suggestion_applied", "ai_suggestion_rolled_back"}:
            target = "name" if field_name == "title" else field_name
            if target in data:
                data[target] = event.new_value
            data["ai_status"] = event.status_label
        return ProductVersionSnapshot(**data)

    def _changes_for_event(self, event: ProductHistoryEvent) -> list[ProductVersionChange]:
        field_name = event.field or event.event_group
        return [
            ProductVersionChange(
                field=field_name,
                field_label=_FIELD_LABELS.get(field_name, field_name),
                old_value=event.old_value,
                new_value=event.new_value,
            )
        ]

    @staticmethod
    def _version_type_for_event(event: ProductHistoryEvent) -> str:
        if event.event_type == "product_imported":
            return "import"
        if event.event_type == "price_changed":
            return "price"
        if event.event_type == "stock_changed":
            return "stock"
        if event.event_type == "ai_suggestion_rolled_back":
            return "rollback"
        if event.event_type == "ai_suggestion_applied":
            return "ai_applied"
        return event.event_group

    @staticmethod
    def _stringify_snapshot_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) if value else None
        if isinstance(value, dict):
            return str(value) if value else None
        return str(value)

    @staticmethod
    def _known_fields(snapshot: ProductVersionSnapshot) -> list[str]:
        data = snapshot.to_dict()
        known = []
        for field_name, value in data.items():
            if value is None:
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            known.append(field_name)
        return sorted(known)
