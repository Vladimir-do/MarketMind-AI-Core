"""Tests for the AI Recommendation Layer."""

from __future__ import annotations

import asyncio
import json
import unittest

from app.ai_recommendation.approval import ApprovalQueue
from app.ai_recommendation.engine import AIRecommendationEngine
from app.ai_recommendation.mock_provider import MockAIProvider
from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.suggestions import (
    AIBatchRecommendationResult,
    AIRecommendationResult,
    AISuggestion,
)
from app.products.findings import AnalysisResult, BatchAnalysisResult, Finding, Recommendation
from app.products.schema import UnifiedProduct


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_product(**overrides) -> UnifiedProduct:
    defaults = {
        "name": "Тестовый товар",
        "source_id": "12345",
        "source_type": "ozon",
        "description": "Описание товара",
        "brand": "Brand",
        "category": "Электроника",
        "price": 1500,
    }
    defaults.update(overrides)
    return UnifiedProduct(**defaults)


def _make_analysis(product=None, findings=None, recommendations=None) -> AnalysisResult:
    return AnalysisResult(
        product=product or _make_product(),
        score=65,
        findings=findings or [
            Finding(
                rule="name_length",
                field="name",
                message="Название слишком короткое",
                severity="warning",
                category="quality",
            )
        ],
        recommendations=recommendations or [
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


class TestMockProvider(unittest.TestCase):
    def test_returns_suggestions(self):
        provider = MockAIProvider()
        response = _run(provider.complete("test prompt"))
        data = json.loads(response.text)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("field", data[0])

    def test_is_available(self):
        self.assertTrue(MockAIProvider().is_available())

    def test_name(self):
        self.assertEqual(MockAIProvider().name(), "mock")


class TestEnginePrompt(unittest.TestCase):
    def test_builds_prompt(self):
        engine = AIRecommendationEngine(MockAIProvider())
        analysis = _make_analysis()
        prompt = engine._build_prompt(
            analysis.product, analysis.findings, analysis.recommendations
        )
        self.assertIn("Тестовый товар", prompt)
        self.assertIn("Название слишком короткое", prompt)
        self.assertIn("Увеличить название", prompt)

    def test_builds_prompt_minimal(self):
        engine = AIRecommendationEngine(MockAIProvider())
        product = UnifiedProduct(name="X", source_id="1", source_type="ozon")
        prompt = engine._build_prompt(product, [], [])
        self.assertIn("X", prompt)


class TestEngineParsing(unittest.TestCase):
    def test_parses_valid_json(self):
        suggestions = [
            {
                "field": "name",
                "suggestion_type": "improve",
                "before": "old",
                "after": "new",
                "reason": "test",
                "confidence": 0.9,
                "source_finding": "f1",
            }
        ]
        result = AIRecommendationEngine._parse_suggestions(json.dumps(suggestions))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].field, "name")
        self.assertAlmostEqual(result[0].confidence, 0.9)

    def test_parses_json_with_fences(self):
        text = '```json\n[{"field": "name", "suggestion_type": "improve", "before": "", "after": "new", "reason": "r", "confidence": 0.7}]```'
        result = AIRecommendationEngine._parse_suggestions(text)
        self.assertEqual(len(result), 1)

    def test_returns_empty_on_invalid(self):
        result = AIRecommendationEngine._parse_suggestions("not json at all")
        self.assertEqual(result, [])

    def test_clamps_confidence(self):
        suggestions = [{"field": "x", "suggestion_type": "fix", "before": "", "after": "", "reason": "", "confidence": 2.0}]
        result = AIRecommendationEngine._parse_suggestions(json.dumps(suggestions))
        self.assertEqual(result[0].confidence, 1.0)

    def test_confidence_string_coercion(self):
        suggestions = [{"field": "x", "suggestion_type": "fix", "before": "", "after": "", "reason": "", "confidence": "0.65"}]
        result = AIRecommendationEngine._parse_suggestions(json.dumps(suggestions))
        self.assertAlmostEqual(result[0].confidence, 0.65)


class TestEngineRecommend(unittest.TestCase):
    def test_recommends_single(self):
        engine = AIRecommendationEngine(MockAIProvider())
        analysis = _make_analysis()
        result = _run(engine.recommend(analysis))
        self.assertIsInstance(result, AIRecommendationResult)
        self.assertEqual(result.product_id, "12345")
        self.assertGreater(len(result.suggestions), 0)
        self.assertGreater(result.overall_confidence, 0)
        self.assertEqual(result.model_used, "mock-v1")

    def test_recommends_batch(self):
        engine = AIRecommendationEngine(MockAIProvider())
        batch = BatchAnalysisResult(
            total=2,
            average_score=45.0,
            products_below_threshold=["p1", "p2"],
        )
        result = _run(engine.recommend_batch(batch))
        self.assertIsInstance(result, AIBatchRecommendationResult)
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.model_used, "mock")

    def test_unavailable_returns_empty(self):
        class UnavailableProvider:
            def is_available(self):
                return False
            def name(self):
                return "unavail"
            async def complete(self, *a, **kw):
                return AIResponse(text="[]", model="unavail")

        engine = AIRecommendationEngine(UnavailableProvider())
        analysis = _make_analysis()
        result = _run(engine.recommend(analysis))
        self.assertEqual(result.suggestions, [])

    def test_overall_confidence(self):
        suggestions = [
            AISuggestion(field="a", suggestion_type="improve", before="", after="", reason="", confidence=0.8),
            AISuggestion(field="b", suggestion_type="expand", before="", after="", reason="", confidence=0.6),
        ]
        self.assertAlmostEqual(AIRecommendationEngine._calculate_overall_confidence(suggestions), 0.7)

    def test_overall_confidence_empty(self):
        self.assertEqual(AIRecommendationEngine._calculate_overall_confidence([]), 0.0)


class TestApprovalQueue(unittest.TestCase):
    def test_add_and_approve(self):
        queue = ApprovalQueue()
        result = AIRecommendationResult(
            product_id="p1",
            suggestions=[
                AISuggestion(field="name", suggestion_type="improve", before="old", after="new", reason="r", confidence=0.9)
            ],
        )
        added = queue.add(result)
        self.assertEqual(len(added), 1)
        self.assertIsNone(added[0].approved)

        approved = queue.approve(added[0].approval_id)
        self.assertIsNotNone(approved)
        self.assertTrue(approved.approved)

    def test_reject(self):
        queue = ApprovalQueue()
        result = AIRecommendationResult(
            product_id="p1",
            suggestions=[
                AISuggestion(field="name", suggestion_type="improve", before="old", after="new", reason="r", confidence=0.9)
            ],
        )
        added = queue.add(result)
        rejected = queue.reject(added[0].approval_id, reason="не подходит")
        self.assertIsNotNone(rejected)
        self.assertFalse(rejected.approved)
        self.assertIn("не подходит", rejected.suggestion.reason)

    def test_get_pending(self):
        queue = ApprovalQueue()
        result = AIRecommendationResult(
            product_id="p1",
            suggestions=[
                AISuggestion(field="name", suggestion_type="improve", before="", after="", reason="", confidence=0.5),
                AISuggestion(field="desc", suggestion_type="expand", before="", after="", reason="", confidence=0.5),
            ],
        )
        added = queue.add(result)
        self.assertEqual(len(queue.get_pending()), 2)
        queue.approve(added[0].approval_id)
        self.assertEqual(len(queue.get_pending()), 1)

    def test_apply_approved(self):
        queue = ApprovalQueue()
        product = _make_product(name="Старое название")
        result = AIRecommendationResult(
            product_id="12345",
            suggestions=[
                AISuggestion(field="name", suggestion_type="improve", before="Старое", after="Новое название", reason="r", confidence=0.9),
                AISuggestion(field="description", suggestion_type="expand", before="", after="Новое описание", reason="r", confidence=0.8),
            ],
        )
        added = queue.add(result)
        queue.approve(added[0].approval_id)
        queue.reject(added[1].approval_id)

        updated = ApprovalQueue.apply_approved(product, queue.get_pending())
        # Only approved ones are in pending — but apply_approved checks .approved flag
        # Let's test with all approvals directly
        updated = ApprovalQueue.apply_approved(product, added)
        self.assertEqual(updated.name, "Новое название")
        self.assertEqual(updated.description, "Описание товара")  # rejected, unchanged

    def test_approve_nonexistent(self):
        queue = ApprovalQueue()
        self.assertIsNone(queue.approve("nonexistent"))
        self.assertIsNone(queue.reject("nonexistent"))


class TestAISuggestionDataclass(unittest.TestCase):
    def test_frozen(self):
        s = AISuggestion(field="x", suggestion_type="improve", before="", after="", reason="", confidence=0.5)
        with self.assertRaises(AttributeError):
            s.field = "y"  # type: ignore[misc]

    def test_defaults(self):
        s = AISuggestion(field="x", suggestion_type="improve", before="", after="", reason="", confidence=0.5)
        self.assertEqual(s.source_finding, "")
        self.assertEqual(s.metadata, {})


if __name__ == "__main__":
    unittest.main()
