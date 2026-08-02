"""Tests for Content Intelligence Pipeline Pydantic contracts."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.content_pipeline.schemas import (
    ContentStrategy,
    FactCheckResult,
    ProductPassport,
    QualityReport,
    SemanticPlan,
    TitleGenerationResult,
)


def _passport(**overrides) -> dict:
    defaults = {
        "product_id": 1,
        "project_id": "proj-1",
        "project_product_id": "pp-1",
        "title": "Термокружка 500 мл",
        "marketplace": "ozon",
    }
    defaults.update(overrides)
    return defaults


class ProductPassportTests(unittest.TestCase):
    def test_valid_passport_round_trips(self):
        passport = ProductPassport(**_passport(brand="Stanley", attributes={"Материал": "Сталь"}))
        dumped = passport.model_dump_json()
        restored = ProductPassport.model_validate_json(dumped)
        self.assertEqual(restored, passport)

    def test_empty_title_rejected(self):
        with self.assertRaises(ValidationError):
            ProductPassport(**_passport(title="   "))

    def test_missing_marketplace_rejected(self):
        with self.assertRaises(ValidationError):
            ProductPassport(**_passport(marketplace=""))

    def test_extra_fields_forbidden(self):
        with self.assertRaises(ValidationError):
            ProductPassport(**_passport(unexpected_field="oops"))


class OtherSchemaTests(unittest.TestCase):
    def test_content_strategy_extra_forbidden(self):
        with self.assertRaises(ValidationError):
            ContentStrategy(
                target_audience="A",
                key_need="B",
                key_selling_proposition="C",
                tone_of_voice="D",
                unexpected="oops",
            )

    def test_content_strategy_minimal(self):
        strategy = ContentStrategy(
            target_audience="Родители",
            key_need="Удобство",
            key_selling_proposition="Держит температуру 12 часов",
            tone_of_voice="дружелюбный",
        )
        self.assertEqual(strategy.usage_scenarios, [])
        self.assertEqual(strategy.formality_level, "professional")

    def test_semantic_plan_defaults(self):
        plan = SemanticPlan()
        self.assertEqual(plan.title_terms, [])
        self.assertEqual(plan.excluded_terms, [])

    def test_title_confidence_clamped(self):
        result = TitleGenerationResult(title="Термокружка", confidence=1.7)
        self.assertEqual(result.confidence, 1.0)
        result2 = TitleGenerationResult(title="Термокружка", confidence=-0.4)
        self.assertEqual(result2.confidence, 0.0)

    def test_fact_check_result_defaults_pass_true(self):
        result = FactCheckResult()
        self.assertTrue(result.passed)

    def test_quality_report_requires_all_fields(self):
        with self.assertRaises(ValidationError):
            QualityReport(seo_score=80)


if __name__ == "__main__":
    unittest.main()
