"""Tests for AI Layer Integration with Pipeline."""

from __future__ import annotations

import asyncio
import unittest

from app.ai_recommendation import AIRecommendationLayer, AIResult, MockAIProvider
from app.ai_recommendation.provider import AIResponse
from app.pipeline import EnrichedProduct, PipelineResult
from app.products.findings import AnalysisResult, BatchAnalysisResult, Finding, Recommendation
from app.products.schema import UnifiedProduct


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_product(**overrides) -> UnifiedProduct:
    defaults = dict(
        name="Тестовый товар",
        source_id="12345",
        source_type="ozon",
        description="Описание товара",
        brand="Brand",
        category="Электроника",
        price=1500,
    )
    defaults.update(overrides)
    return UnifiedProduct(**defaults)


def _make_analysis(product=None) -> AnalysisResult:
    return AnalysisResult(
        product=product or _make_product(),
        score=65,
        findings=[
            Finding(
                rule="name_length",
                field="name",
                message="Название слишком короткое",
                severity="warning",
                category="quality",
            )
        ],
        recommendations=[
            Recommendation(
                finding=Finding(
                    rule="name_length",
                    field="name",
                    message="Название слишком короткое",
                    severity="warning",
                    category="quality",
                ),
                action="Увеличить название",
                priority=1,
                description="Добавить ключевые слова в название",
            )
        ],
        tier="fair",
    )


def _make_pipeline_result(product_ids=None) -> PipelineResult:
    if product_ids is None:
        product_ids = ["12345"]

    enriched = []
    for pid in product_ids:
        product = _make_product(source_id=pid)
        analysis = _make_analysis(product)
        enriched.append(EnrichedProduct(product=product, analysis=analysis))

    return PipelineResult(
        enriched=enriched,
        batch_analysis=BatchAnalysisResult(
            total=len(product_ids),
            average_score=65.0,
            products_below_threshold=product_ids,
        ),
    )


class TestPostProcessWithMockProvider(unittest.TestCase):
    def test_returns_ai_result(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        self.assertIsInstance(result, AIResult)

    def test_recommendations_populated(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        self.assertGreater(result.recommendations.total_suggestions, 0)
        self.assertEqual(len(result.recommendations.results), 1)

    def test_approval_queue_populated(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        pending = result.approval_queue.get_pending()
        self.assertGreater(len(pending), 0)


class TestPostProcessEmptyPipeline(unittest.TestCase):
    def test_empty_enriched(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = PipelineResult(enriched=[], batch_analysis=None)
        result = _run(layer.post_process(pipeline_result))
        self.assertEqual(result.recommendations.total_suggestions, 0)
        self.assertEqual(len(result.approval_queue.get_pending()), 0)

    def test_no_analysis(self):
        layer = AIRecommendationLayer(MockAIProvider())
        product = _make_product()
        pipeline_result = PipelineResult(
            enriched=[EnrichedProduct(product=product, analysis=None)],
            batch_analysis=None,
        )
        result = _run(layer.post_process(pipeline_result))
        self.assertEqual(result.recommendations.total_suggestions, 0)


class TestPostProcessAIUnavailable(unittest.TestCase):
    def test_unavailable_provider(self):
        class UnavailableProvider:
            def is_available(self):
                return False

            def name(self):
                return "unavailable"

            async def complete(self, *a, **kw):
                return AIResponse(text="[]", model="unavailable")

        layer = AIRecommendationLayer(UnavailableProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        self.assertIsInstance(result, AIResult)
        self.assertEqual(result.recommendations.total_suggestions, 0)


class TestPostProcessAIErrorGraceful(unittest.TestCase):
    def test_error_continues(self):
        class FailingProvider:
            def is_available(self):
                return True

            def name(self):
                return "failing"

            async def complete(self, *a, **kw):
                raise RuntimeError("API error")

        layer = AIRecommendationLayer(FailingProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        self.assertIsInstance(result, AIResult)
        self.assertEqual(result.recommendations.total_suggestions, 0)


class TestAIResultMetadata(unittest.TestCase):
    def test_contains_metadata(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result()
        result = _run(layer.post_process(pipeline_result))
        self.assertIn("products_processed", result.ai_metadata)
        self.assertIn("elapsed_ms", result.ai_metadata)
        self.assertIn("provider", result.ai_metadata)
        self.assertEqual(result.ai_metadata["products_processed"], 1)
        self.assertEqual(result.ai_metadata["provider"], "mock")


class TestApprovalQueuePopulated(unittest.TestCase):
    def test_queue_has_items(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result(["p1", "p2"])
        result = _run(layer.post_process(pipeline_result))
        pending = result.approval_queue.get_pending()
        self.assertGreaterEqual(len(pending), 2)


class TestFullPipelineWithAI(unittest.TestCase):
    def test_multiple_products(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result(["p1", "p2", "p3"])
        result = _run(layer.post_process(pipeline_result))
        self.assertEqual(len(result.recommendations.results), 3)
        self.assertEqual(result.ai_metadata["products_processed"], 3)
        self.assertGreater(result.recommendations.total_suggestions, 0)

    def test_batch_metadata(self):
        layer = AIRecommendationLayer(MockAIProvider())
        pipeline_result = _make_pipeline_result(["p1", "p2"])
        result = _run(layer.post_process(pipeline_result))
        self.assertEqual(result.recommendations.model_used, "mock")


if __name__ == "__main__":
    unittest.main()
