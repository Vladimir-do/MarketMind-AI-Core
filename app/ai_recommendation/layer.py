"""AI Recommendation Layer — post-pipeline integration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.ai_recommendation.approval import ApprovalQueue
from app.ai_recommendation.engine import AIRecommendationEngine
from app.ai_recommendation.suggestions import AIBatchRecommendationResult

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider
    from app.pipeline import PipelineResult

logger = logging.getLogger(__name__)


@dataclass
class AIResult:
    """Result of AI post-processing on a pipeline result."""

    recommendations: AIBatchRecommendationResult
    approval_queue: ApprovalQueue
    ai_metadata: dict[str, Any] = field(default_factory=dict)


class AIRecommendationLayer:
    """Optional AI layer that runs after the pipeline."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self._engine = AIRecommendationEngine(provider)

    async def post_process(self, pipeline_result: PipelineResult) -> AIResult:
        """Run AI recommendations on enriched products from the pipeline."""
        start = time.monotonic()
        queue = ApprovalQueue()
        results = []

        # Build product_id → AnalysisResult mapping
        analysis_map: dict[str, Any] = {}
        for ep in pipeline_result.enriched:
            if ep.analysis is not None:
                analysis_map[ep.product.source_id] = ep.analysis

        # Filter to products below threshold (or all if no batch_analysis)
        if pipeline_result.batch_analysis and pipeline_result.batch_analysis.products_below_threshold:
            target_ids = set(pipeline_result.batch_analysis.products_below_threshold)
        else:
            target_ids = set(analysis_map.keys())

        # Generate recommendations for each target product
        for product_id in target_ids:
            analysis = analysis_map.get(product_id)
            if analysis is None:
                continue
            try:
                result = await self._engine.recommend(analysis)
                results.append(result)
                queue.add(result)
            except Exception:
                logger.warning("AI recommendation failed for product %s", product_id, exc_info=True)

        batch_result = self._build_batch_result(results)
        elapsed_ms = (time.monotonic() - start) * 1000

        return AIResult(
            recommendations=batch_result,
            approval_queue=queue,
            ai_metadata={
                "products_processed": len(results),
                "elapsed_ms": round(elapsed_ms, 1),
                "provider": self._provider.name(),
            },
        )

    def _build_batch_result(self, results: list) -> AIBatchRecommendationResult:
        """Build a batch result from individual product results."""
        total_suggestions = sum(len(r.suggestions) for r in results)
        high_confidence = sum(
            1 for r in results for s in r.suggestions if s.confidence >= 0.8
        )
        return AIBatchRecommendationResult(
            results=results,
            total_suggestions=total_suggestions,
            high_confidence_count=high_confidence,
            model_used=self._provider.name(),
        )
