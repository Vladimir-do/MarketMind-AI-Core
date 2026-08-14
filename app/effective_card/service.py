"""Effective product card service for project-scoped workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, select

from app.ai_recommendation.suggestions import AISuggestion
from app.database import Database, ProductCardVersion, ProjectProduct
from app.editor.schemas import normalize_card_payload
from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct
from app.projects.service import ProjectService
from app.seo_intelligence import (
    FORBIDDEN_MARKETING_WORDS,
    GENERIC_PRODUCT_TYPES,
    SEOFinding,
    audit_unified_product_seo,
)

if TYPE_CHECKING:
    from app.seo_history import SEOHistoryService


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

    def __init__(self, db: Database, seo_history: SEOHistoryService | None = None) -> None:
        self._db = db
        self._seo_history = seo_history

    async def get_effective_card(self, project_id: str, product_id: int) -> EffectiveProductCard:
        async with self._db.session() as session:
            project_product = await ProjectService(self._db).get_project_product(
                project_id, product_id, session=session
            )
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

    async def list_effective_cards_with_seo_summary(self, project_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        cards = await self.list_effective_cards(project_id, limit=limit, offset=offset)
        result = []
        for card in cards:
            seo = audit_unified_product_seo(_unified_from_snapshot(card.effective_snapshot, card.product_id))
            result.append({
                "card": card,
                "seo_score": seo.score,
                "seo_tier": seo.tier,
                "seo_ready": seo.ready,
            })
        return result

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

    async def seo(self, project_id: str, product_id: int) -> dict[str, Any]:
        card = await self.get_effective_card(project_id, product_id)
        source = audit_unified_product_seo(_unified_from_snapshot(card.source_snapshot, product_id))
        effective = audit_unified_product_seo(_unified_from_snapshot(card.effective_snapshot, product_id))

        history_items: list[dict[str, Any]] = []
        if self._seo_history is not None:
            snapshots = await self._seo_history.get_history(project_id, product_id, limit=5)
            history_items = [s.to_dict() for s in snapshots]

        return {
            "project_id": project_id,
            "product_id": product_id,
            "source": _seo_to_dict(source),
            "effective": _seo_to_dict(effective),
            "warnings": card.warnings,
            "history": history_items,
        }

    async def seo_suggestions(self, project_id: str, product_id: int) -> list[AISuggestion]:
        """SEO-рекомендации в формате AISuggestion для approval workflow."""
        card = await self.get_effective_card(project_id, product_id)
        product = _unified_from_snapshot(card.effective_snapshot, product_id)
        audit = audit_unified_product_seo(product)
        suggestions = []
        for finding in audit.findings:
            suggestion = _finding_to_suggestion(card, finding)
            if suggestion is not None:
                suggestions.append(suggestion)
        return suggestions

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
    tags = snapshot.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.replace(";", ",").split(",") if item.strip()]
    return UnifiedProduct(
        name=str(snapshot.get("title") or ""),
        source_id=str(snapshot.get("external_product_id") or product_id),
        source_type=str(snapshot.get("marketplace") or "unknown"),
        description=snapshot.get("description"),
        brand=snapshot.get("brand"),
        price=snapshot.get("price"),
        old_price=snapshot.get("old_price"),
        discount_pct=snapshot.get("discount_pct"),
        image_urls=list(snapshot.get("image_urls") or []),
        attributes=dict(snapshot.get("attributes") or {}),
        category=snapshot.get("category"),
        sku=snapshot.get("sku") or snapshot.get("external_product_id"),
        weight_g=snapshot.get("weight_g"),
        width_mm=snapshot.get("width_mm"),
        height_mm=snapshot.get("height_mm"),
        depth_mm=snapshot.get("depth_mm"),
        source_url=snapshot.get("source_url"),
        tags=list(tags),
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


def _seo_to_dict(seo) -> dict[str, Any]:
    return {
        "score": seo.score,
        "tier": seo.tier,
        "ready": seo.ready,
        "findings": [
            {
                "rule": item.rule,
                "field": item.field,
                "message": item.message,
                "severity": item.severity,
            }
            for item in seo.findings
        ],
        "recommendations": [
            {
                "field": item.field,
                "action": item.action,
                "priority": item.priority,
                "reason": item.reason,
            }
            for item in seo.recommendations
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


# --- SEO Suggestions helpers ---

_FINDING_TO_FIELD = {
    "name": "title",
    "description": "description",
    "keywords": "tags",
}


def _finding_to_suggestion(card: EffectiveProductCard, finding: SEOFinding) -> AISuggestion | None:
    """Convert a finding into a factual suggestion when a safe replacement exists."""
    snapshot_field = _FINDING_TO_FIELD.get(finding.field)
    if snapshot_field is None:
        return None

    snapshot = card.effective_snapshot
    current_value = snapshot.get(snapshot_field, "")
    if isinstance(current_value, list):
        current_value = ", ".join(str(v) for v in current_value)
    current_value = str(current_value or "")
    metadata = {
        "source": "seo_audit",
        "project_id": card.project_id,
        "project_product_id": card.project_product_id,
        "product_name": snapshot.get("title") or str(card.product_id),
    }

    if finding.rule == "seo_title_forbidden_words":
        after = _remove_forbidden_words(current_value)
        if after == current_value:
            return None
        return AISuggestion(
            field="title",
            suggestion_type="rewrite",
            before=current_value,
            after=after,
            reason=finding.message,
            confidence=0.6,
            source_finding=finding.rule,
            metadata=metadata,
        )

    if finding.rule == "seo_description_forbidden_words":
        after = _remove_forbidden_words(current_value)
        if after == current_value:
            return None
        return AISuggestion(
            field="description",
            suggestion_type="rewrite",
            before=current_value,
            after=after,
            reason=finding.message,
            confidence=0.6,
            source_finding=finding.rule,
            metadata=metadata,
        )

    if finding.rule == "seo_keywords_few":
        name = str(snapshot.get("title") or "")
        extracted = _extract_keywords_from_name(name)
        if not extracted:
            return None
        existing_tags = snapshot.get("tags") or []
        if isinstance(existing_tags, str):
            existing_tags = [t.strip() for t in existing_tags.split(",") if t.strip()]
        new_tags = list(dict.fromkeys(existing_tags + extracted))
        after = ", ".join(new_tags)
        return AISuggestion(
            field="tags",
            suggestion_type="expand",
            before=", ".join(existing_tags) if existing_tags else "",
            after=after,
            reason=finding.message,
            confidence=0.5,
            source_finding=finding.rule,
            metadata=metadata,
        )

    return None


def _remove_forbidden_words(text: str) -> str:
    """Удаляет запрещённые маркетинговые слова из текста."""
    words = text.split()
    cleaned = []
    for word in words:
        clean = word.lower().rstrip(".,!?;:\"'()[]{}")
        if clean not in FORBIDDEN_MARKETING_WORDS:
            cleaned.append(word)
    return " ".join(cleaned)


def _extract_keywords_from_name(name: str) -> list[str]:
    """Извлекает ключевые слова из названия товара."""
    import re
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", name.lower())
    return [
        t
        for t in tokens
        if t not in GENERIC_PRODUCT_TYPES
        and t not in FORBIDDEN_MARKETING_WORDS
        and not t.isdigit()
    ][:6]
