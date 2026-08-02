"""Tests for the deterministic Fact Checker."""

from __future__ import annotations

import unittest

from app.content_pipeline.fact_checker import extract_claims, run_fact_check, verify_claim
from app.content_pipeline.schemas import ProductPassport


def _passport(**overrides) -> ProductPassport:
    defaults = dict(
        product_id=1,
        project_id="proj-1",
        project_product_id="pp-1",
        title="Термокружка",
        marketplace="ozon",
        weight_g=450,
        width_mm=80,
        height_mm=200,
        depth_mm=80,
        attributes={"Материал": "Нержавеющая сталь", "Цвет": "Черный"},
    )
    defaults.update(overrides)
    return ProductPassport(**defaults)


class ExtractClaimsTests(unittest.TestCase):
    def test_extracts_weight_claim(self):
        claims = extract_claims("Вес товара 450 г, удобно носить с собой")
        weight_claims = [c for c in claims if c.claim_type == "weight"]
        self.assertEqual(len(weight_claims), 1)
        self.assertEqual(weight_claims[0].value, "450")

    def test_extracts_warranty_claim(self):
        claims = extract_claims("Гарантия 2 года на все дефекты")
        warranty = [c for c in claims if c.claim_type == "warranty"]
        self.assertEqual(len(warranty), 1)

    def test_no_claims_in_empty_text(self):
        self.assertEqual(extract_claims(""), [])


class VerifyClaimTests(unittest.TestCase):
    def test_confirmed_weight_within_tolerance(self):
        claims = extract_claims("Вес 450 г")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "confirmed")

    def test_confirmed_weight_rounding_tolerance(self):
        claims = extract_claims("Вес около 460 г")  # в пределах 5% от 450
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "confirmed")

    def test_contradicted_weight_outside_tolerance(self):
        claims = extract_claims("Вес 900 г")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "contradicted")

    def test_weight_unverifiable_without_passport_field(self):
        claims = extract_claims("Вес 450 г")
        verdict = verify_claim(claims[0], _passport(weight_g=None))
        self.assertEqual(verdict.verdict, "unverifiable")

    def test_dimension_matches_any_axis(self):
        claims = extract_claims("Высота 200 мм")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "confirmed")
        self.assertEqual(verdict.passport_field, "height_mm")

    def test_dimension_cm_converted_to_mm(self):
        claims = extract_claims("Высота 20 см")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "confirmed")

    def test_material_confirmed(self):
        claims = extract_claims("Материал: нержавеющая сталь, не ржавеет")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "confirmed")

    def test_percent_is_unverifiable_no_passport_field(self):
        claims = extract_claims("Скидка 20%")
        verdict = verify_claim(claims[0], _passport())
        self.assertEqual(verdict.verdict, "unverifiable")


class RunFactCheckTests(unittest.TestCase):
    def test_passed_true_when_no_contradictions(self):
        result = run_fact_check("Вес 450 г, материал нержавеющая сталь", _passport())
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.confirmed_count, 1)

    def test_passed_false_on_contradiction(self):
        result = run_fact_check("Вес 900 г", _passport())
        self.assertFalse(result.passed)
        self.assertEqual(result.contradicted_count, 1)


if __name__ == "__main__":
    unittest.main()
