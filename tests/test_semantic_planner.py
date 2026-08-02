"""Tests for the deterministic Semantic Planner (zone distribution)."""

from __future__ import annotations

import unittest

from app.content_pipeline.schemas import ProductPassport
from app.content_pipeline.semantic_planner import build_semantic_plan, semantic_plan_for_passport
from app.semantic_core import SemanticCore
from app.seo_rules import get_marketplace_rules


def _core(**overrides) -> SemanticCore:
    defaults = {
        "primary_terms": ["термокружка"],
        "secondary_terms": ["нержавеющая", "герметичная"],
        "long_tail_terms": ["для кофе", "в дорогу"],
        "brand_terms": ["stanley"],
        "attribute_terms": ["500мл"],
        "category_terms": ["посуда"],
        "forbidden_terms": ["лучший"],
        "noisy_terms": ["AB123"],
        "total_terms": 9,
        "coverage_score": 0.5,
        "junk_ratio": 0.2,
    }
    defaults.update(overrides)
    return SemanticCore(**defaults)


class SemanticPlannerTests(unittest.TestCase):
    def test_distribution_has_no_overlap(self):
        plan = build_semantic_plan(_core())
        zones = [set(plan.title_terms), set(plan.benefits_terms), set(plan.description_terms)]
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                self.assertEqual(zones[i] & zones[j], set())

    def test_forbidden_and_noisy_go_to_excluded(self):
        plan = build_semantic_plan(_core())
        self.assertIn("лучший", plan.excluded_terms)
        self.assertIn("AB123", plan.excluded_terms)

    def test_primary_and_brand_prioritized_for_title(self):
        plan = build_semantic_plan(_core())
        self.assertIn("термокружка", plan.title_terms)
        self.assertIn("stanley", plan.title_terms)

    def test_title_budget_respects_marketplace_title_max(self):
        core = _core(primary_terms=[f"term{i}" for i in range(30)])
        tight_rules = get_marketplace_rules("wildberries")  # title_max=60, короче ozon
        plan = build_semantic_plan(core, rules=tight_rules)
        self.assertLess(len(plan.title_terms), 30)

    def test_competitor_gap_terms_empty_without_competitors(self):
        plan = build_semantic_plan(_core())
        self.assertEqual(plan.competitor_gap_terms, [])

    def test_competitor_gap_terms_via_semantic_plan_for_passport(self):
        passport = ProductPassport(
            product_id=1,
            project_id="proj-1",
            project_product_id="pp-1",
            title="Термокружка Stanley 500 мл",
            brand="Stanley",
            marketplace="ozon",
        )
        _, plan_without = semantic_plan_for_passport(passport)
        self.assertEqual(plan_without.competitor_gap_terms, [])

        _, plan_with = semantic_plan_for_passport(
            passport,
            competitor_names=[
                "Термокружка Contigo вакуумная 500мл",
                "Термокружка Contigo вакуумная спортивная",
                "Термос вакуумный Contigo 500мл",
            ],
        )
        self.assertIn("contigo", plan_with.competitor_gap_terms)

    def test_semantic_plan_for_passport_builds_core_and_plan(self):
        passport = ProductPassport(
            product_id=1,
            project_id="proj-1",
            project_product_id="pp-1",
            title="Термокружка Stanley 500 мл нержавеющая сталь",
            brand="Stanley",
            marketplace="ozon",
            attributes={"Материал": "Сталь", "Объём": "500 мл"},
            tags=["термос", "кружка"],
        )
        core, plan = semantic_plan_for_passport(passport)
        self.assertIsInstance(core, SemanticCore)
        self.assertTrue(plan.title_terms or plan.benefits_terms)


if __name__ == "__main__":
    unittest.main()
