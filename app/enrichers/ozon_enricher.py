"""Ozon-specific enrichment strategy wrapping card_filler logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.card_filler import OzonCardDraft, build_ozon_card_draft, build_ozon_card_quality_report
from app.enrichers import EnrichmentResult

if TYPE_CHECKING:
    from app.products.schema import UnifiedProduct


class OzonEnrichmentStrategy:
    """Enriches products using Ozon card draft generation."""

    def enrich(self, product: UnifiedProduct) -> EnrichmentResult:
        draft = self._build_draft(product)
        quality_score = 0
        needs_review: list[str] = []
        warnings: list[str] = []

        if draft:
            quality_report = build_ozon_card_quality_report(draft)
            quality_score = quality_report.score
            needs_review = quality_report.missing
            warnings = quality_report.warnings

        return EnrichmentResult(
            product=product,
            metadata={
                "draft": draft,
                "quality_score": quality_score,
                "needs_review": needs_review,
                "warnings": warnings,
            },
        )

    def _build_draft(self, product: UnifiedProduct) -> OzonCardDraft | None:
        try:
            task_text = product.to_card_task()
            if not task_text.strip():
                return None
            return build_ozon_card_draft(task_text)
        except Exception:
            return None
