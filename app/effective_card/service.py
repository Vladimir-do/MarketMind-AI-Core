"""Effective product card service for project-scoped workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import desc, select

from app.database import Database, ProductCardVersion, ProjectProduct
from app.editor.schemas import normalize_card_payload
from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct
from app.projects.service import ProjectNotFoundError


@dataclass(frozen=True)
class EffectiveProductCard:
    product_id: int
    project_id: str
    project_product_id: str
    source_snapshot: dict[str, Any]
    applied_snapshot: dict[str, Any] | None
    effective_snapshot: dict[str, Any]
    latest_version_id: str | None
    latest_version_number: int | None
    overridden_fields: list[str] = field(default_factory=list)
    is_manually_modified: bool = False
    source_updated_at: str | None = None
    effective_updated_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EffectiveProductCardService:
    """Builds project-specific effective cards from source data and applied versions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_effective_card(self, project_id: str, product_id: int) -> EffectiveProductCard:
        async with self._db.session() as session:
            project_product = await self._get_project_product(session, project_id, product_id)
            version = await self._latest_version(session, project_product)
            return self._build_card(project_product, version)

    async def list_effective_cards(self, project_id: str, *, limit: int = 100, offset: int = 0) -> list[EffectiveProductCard]:
        async with self._db.session() as session:
            result = await session.execute(
                select(ProjectProduct)
                .where(ProjectProduct.project_id == project_id)
                .order_by(desc(ProjectProduct.updated_at))
                .limit(max(1, min(limit, 500)))
                .offset(max(offset, 0))
            )
            cards = []
            for project_product in result.scalars().all():
                version = await self._latest_version(session, project_product)
                cards.append(self._build_card(project_product, version))
            return cards

    async def quality(self, project_id: str, product_id: int) -> dict[str, Any]:
        card = await self.get_effective_card(project_id, product_id)
        analyzer = ProductAnalyzer()
        source = analyzer.analyze(_unified_from_snapshot(card.source_snapshot, product_id))
        effective = analyzer.analyze(_unified_from_snapshot(card.effective_snapshot, product_id))
        return {
            "project_id": project_id,
            "product_id": product_id,
            "source": _analysis_to_dict(source),
            "effective": _analysis_to_dict(effective),
            "draft_preview": None,
            "warnings": card.warnings,
        }

    async def draft_quality_preview(self, project_id: str, product_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        card = await self.get_effective_card(project_id, product_id)
        preview = normalize_card_payload({**card.effective_snapshot, **payload})
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(_unified_from_snapshot(preview, product_id))
        return {
            "project_id": project_id,
            "product_id": product_id,
            "draft_preview": _analysis_to_dict(result),
            "warnings": card.warnings,
        }

    @staticmethod
    async def _get_project_product(session, project_id: str, product_id: int) -> ProjectProduct:
        record = await session.scalar(
            select(ProjectProduct)
            .where(ProjectProduct.project_id == project_id)
            .where(ProjectProduct.product_id == product_id)
        )
        if record is None:
            raise ProjectNotFoundError("Товар не найден в проекте")
        return record

    @staticmethod
    async def _latest_version(session, project_product: ProjectProduct) -> ProductCardVersion | None:
        result = await session.execute(
            select(ProductCardVersion)
            .where(ProductCardVersion.project_id == project_product.project_id)
            .where(ProductCardVersion.project_product_id == project_product.project_product_id)
            .order_by(desc(ProductCardVersion.version_number))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _build_card(project_product: ProjectProduct, version: ProductCardVersion | None) -> EffectiveProductCard:
        raw_source = json.loads(project_product.latest_source_snapshot_json or "{}")
        source_provenance = raw_source.get("_provenance") or {}
        source = _without_internal_fields(raw_source)
        applied = _without_internal_fields(json.loads(version.snapshot_json)) if version is not None else None
        effective = applied or source
        overridden = sorted(
            field for field in set(source) | set(effective)
            if source.get(field) != effective.get(field)
        )
        provenance = _build_provenance(project_product, source, effective, version, source_provenance)
        warnings = []
        if applied and project_product.source_snapshot_hash != project_product.latest_source_snapshot_hash:
            warnings.append("Исходное значение изменилось. Ручная версия сохранена.")
        return EffectiveProductCard(
            product_id=project_product.product_id,
            project_id=project_product.project_id,
            project_product_id=project_product.project_product_id,
            source_snapshot=source,
            applied_snapshot=applied,
            effective_snapshot=effective,
            latest_version_id=version.version_id if version is not None else None,
            latest_version_number=version.version_number if version is not None else None,
            overridden_fields=overridden,
            is_manually_modified=bool(applied),
            source_updated_at=project_product.source_updated_at.isoformat() if project_product.source_updated_at else None,
            effective_updated_at=project_product.effective_updated_at.isoformat() if project_product.effective_updated_at else None,
            warnings=warnings,
            provenance=provenance,
        )


def _unified_from_snapshot(snapshot: dict[str, Any], product_id: int) -> UnifiedProduct:
    return UnifiedProduct(
        name=str(snapshot.get("title") or ""),
        source_id=str(snapshot.get("external_product_id") or product_id),
        source_type=str(snapshot.get("marketplace") or "unknown"),
        description=snapshot.get("description"),
        brand=snapshot.get("brand"),
        price=snapshot.get("price"),
        image_urls=list(snapshot.get("image_urls") or []),
        attributes=dict(snapshot.get("attributes") or {}),
        marketplace=snapshot.get("marketplace"),
        availability=str(snapshot.get("availability") or "unknown"),
    )


def _analysis_to_dict(analysis) -> dict[str, Any]:
    return {
        "score": analysis.score,
        "tier": analysis.tier,
        "findings": [
            {
                "rule": item.rule,
                "field": item.field,
                "message": item.message,
                "severity": item.severity,
                "category": item.category,
            }
            for item in analysis.findings
        ],
    }


def _build_provenance(
    project_product: ProjectProduct,
    source: dict[str, Any],
    effective: dict[str, Any],
    version: ProductCardVersion | None,
    source_provenance: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    source_row = project_product.source_row_index
    for field_name in sorted(set(source) | set(effective)):
        is_overridden = version is not None and source.get(field_name) != effective.get(field_name)
        result[field_name] = {
            "source_type": "manual_version" if is_overridden else "imported_file",
            "source_file_id": project_product.source_file_id,
            "source_row": source_row,
            "source_column": _source_column_for_field(field_name, source, source_provenance),
            "original_value": source.get(field_name),
            "normalized_value": effective.get(field_name),
            "version_id": version.version_id if is_overridden and version is not None else None,
            "draft_id": None,
            "changed_at": version.created_at.isoformat() if is_overridden and version is not None else None,
            "reason": version.comment if is_overridden and version is not None else "Импортировано из файла заказчика",
            "actor": version.actor_id if is_overridden and version is not None else "operator",
        }
    return result


def _source_column_for_field(field: str, source: dict[str, Any], source_provenance: dict[str, Any]) -> str | None:
    field_sources = source_provenance.get("field_sources") or {}
    if field in field_sources:
        return str(field_sources[field])
    attributes = source.get("attributes") or {}
    marker = f"source:{field}"
    if marker in attributes:
        return field
    return field if field in source else None


def _without_internal_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if not str(key).startswith("_")}
