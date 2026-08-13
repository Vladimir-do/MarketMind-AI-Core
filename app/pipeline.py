"""Import pipeline: import → validate → enrich → analyze."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from app.enrichers.ozon_enricher import OzonEnrichmentStrategy
from app.importers.registry import import_file, import_string
from app.products.analyzer import ProductAnalyzer
from app.products.validator import ProductValidator, ValidationError

if TYPE_CHECKING:
    from app.enrichers import EnrichmentStrategy
    from app.products.schema import UnifiedProduct
    from app.products.findings import AnalysisResult, BatchAnalysisResult
    from app.importers.base import ImportResult, ImportRowError
    from pathlib import Path


@dataclass
class EnrichedProduct:
    """Product with enrichment metadata."""

    product: UnifiedProduct
    draft: Any = None
    quality_score: int = 0
    needs_review: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis: AnalysisResult | None = None


@dataclass
class PipelineResult:
    """Result of a pipeline run."""

    enriched: list[EnrichedProduct] = field(default_factory=list)
    errors: list[ValidationError | ImportRowError] = field(default_factory=list)
    import_metadata: dict[str, Any] = field(default_factory=dict)
    enrichment_metadata: dict[str, Any] = field(default_factory=dict)
    batch_analysis: BatchAnalysisResult | None = None
    analysis_metadata: dict[str, Any] = field(default_factory=dict)


class ImportPipeline:
    """Pipeline: import → validate → enrich."""

    def __init__(self, limit: int | None = None, strategy: EnrichmentStrategy | None = None):
        self.limit = limit
        self.strategy = strategy if strategy is not None else OzonEnrichmentStrategy()
        self.validator = ProductValidator()

    def run_file(self, path: str | Path, limit: int | None = None) -> PipelineResult:
        """Run pipeline on a file."""
        effective_limit = limit or self.limit
        import_result = import_file(path)
        return self._process_import_result(import_result, effective_limit)

    def run_string(self, content: str, filename: str) -> PipelineResult:
        """Run pipeline on string content."""
        import_result = import_string(content, filename)
        return self._process_import_result(import_result, self.limit)

    def run_products(self, products: list[UnifiedProduct]) -> PipelineResult:
        """Run pipeline on pre-imported products."""
        validated_products, validation_errors = self.validator.validate(products)
        enriched = [self._enrich_product(p) for p in validated_products]

        for ep in enriched:
            ep.analysis = self._analyze_product(ep)

        batch_analysis = self._analyze_batch(enriched)
        analysis_metadata = {
            "analyzed": len(enriched),
            "average_score": batch_analysis.average_score,
            "below_threshold": len(batch_analysis.products_below_threshold),
            "tier_distribution": batch_analysis.score_distribution,
            "top_issues": [{"rule": r.finding.rule, "action": r.action, "priority": r.priority}
                           for r in batch_analysis.top_recommendations],
        }

        return PipelineResult(
            enriched=enriched,
            errors=validation_errors,
            import_metadata={"source": "direct", "total_products": len(products)},
            enrichment_metadata={
                "total": len(products),
                "validated": len(validated_products),
                "enriched": len(enriched),
            },
            batch_analysis=batch_analysis,
            analysis_metadata=analysis_metadata,
        )

    def _process_import_result(self, import_result: ImportResult, limit: int | None) -> PipelineResult:
        """Process an ImportResult through validation and enrichment."""
        products = import_result.products
        if limit:
            products = products[:limit]

        validated_products, validation_errors = self.validator.validate(products)
        enriched = [self._enrich_product(p) for p in validated_products]

        for ep in enriched:
            ep.analysis = self._analyze_product(ep)

        batch_analysis = self._analyze_batch(enriched)
        analysis_metadata = {
            "analyzed": len(enriched),
            "average_score": batch_analysis.average_score,
            "below_threshold": len(batch_analysis.products_below_threshold),
            "tier_distribution": batch_analysis.score_distribution,
            "top_issues": [{"rule": r.finding.rule, "action": r.action, "priority": r.priority}
                           for r in batch_analysis.top_recommendations],
        }

        all_errors: list[ValidationError | ImportRowError] = import_result.errors + validation_errors

        return PipelineResult(
            enriched=enriched,
            errors=all_errors,
            import_metadata=import_result.metadata,
            enrichment_metadata={
                "total_imported": len(import_result.products),
                "after_limit": len(products),
                "validated": len(validated_products),
                "enriched": len(enriched),
            },
            batch_analysis=batch_analysis,
            analysis_metadata=analysis_metadata,
        )

    def _enrich_product(self, product: UnifiedProduct) -> EnrichedProduct:
        """Enrich a single product with card draft and quality scoring."""
        normalized = self._normalize_text(product)
        filled = self._fill_missing_data(normalized)

        if self.strategy is None:
            return EnrichedProduct(product=filled)

        result = self.strategy.enrich(filled)
        return EnrichedProduct(
            product=result.product,
            draft=result.metadata.get("draft"),
            quality_score=result.metadata.get("quality_score", 0),
            needs_review=result.metadata.get("needs_review", []),
            warnings=result.metadata.get("warnings", []),
        )

    def _analyze_product(self, ep: EnrichedProduct) -> AnalysisResult:
        analyzer = ProductAnalyzer()
        return analyzer.analyze(ep.product)

    def _analyze_batch(self, products: list[EnrichedProduct]) -> BatchAnalysisResult:
        analyzer = ProductAnalyzer()
        return analyzer.analyze_batch([ep.product for ep in products])

    def _normalize_text(self, product: UnifiedProduct) -> UnifiedProduct:
        """Clean whitespace in text fields."""
        product.name = " ".join(product.name.split()) if product.name else ""
        if product.description:
            product.description = " ".join(product.description.split())
        if product.brand:
            product.brand = " ".join(product.brand.split())
        if product.category:
            product.category = " ".join(product.category.split())
        return product

    def _fill_missing_data(self, product: UnifiedProduct) -> UnifiedProduct:
        """Fill derived fields if source data is present."""
        if product.discount_pct is None and product.price is not None and product.old_price is not None:
            if product.old_price > product.price:
                discount = round((1 - product.price / product.old_price) * 100)
                product.discount_pct = discount
        return product

