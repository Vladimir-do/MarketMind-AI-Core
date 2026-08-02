"""Tests for SEO Auditor / Marketplace Validator thin adapters."""

from __future__ import annotations

import unittest

from app.content_pipeline.marketplace_validator import validate_for_marketplace
from app.content_pipeline.schemas import ProductPassport
from app.content_pipeline.seo_auditor import audit_draft


def _weak_passport() -> ProductPassport:
    return ProductPassport(
        product_id=1,
        project_id="proj-1",
        project_product_id="pp-1",
        title="Товар",
        marketplace="ozon",
    )


def _strong_passport() -> ProductPassport:
    return ProductPassport(
        product_id=1,
        project_id="proj-1",
        project_product_id="pp-1",
        title="Термокружка Stanley 500 мл нержавеющая сталь для походов и офиса",
        description="Термокружка Stanley из нержавеющей стали объёмом 500 мл. " * 15,
        brand="Stanley",
        category="Термокружки",
        marketplace="ozon",
        attributes={"Материал": "Сталь", "Объём": "500 мл", "Цвет": "Черный", "Тип крышки": "Клапан", "Вес": "450 г"},
        tags=["термокружка", "stanley", "500мл", "нержавеющая сталь", "термос", "для похода", "подарок", "офис"],
        image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg", "https://example.com/3.jpg"],
    )


class SEOAuditorTests(unittest.TestCase):
    def test_weak_passport_scores_low(self):
        summary = audit_draft(_weak_passport())
        self.assertLess(summary.score, 75)
        self.assertFalse(summary.ready)

    def test_strong_passport_scores_higher(self):
        weak = audit_draft(_weak_passport())
        strong = audit_draft(_strong_passport())
        self.assertGreater(strong.score, weak.score)

    def test_title_description_overrides_are_used(self):
        base = audit_draft(_weak_passport())
        overridden = audit_draft(
            _weak_passport(),
            title="Совсем другое название которое значительно длиннее исходного",
        )
        self.assertNotEqual(base.score, overridden.score)


class MarketplaceValidatorTests(unittest.TestCase):
    def test_weak_passport_not_ready_with_blocking_issues_or_score(self):
        result = validate_for_marketplace(_weak_passport())
        self.assertFalse(result.ready)

    def test_strong_passport_more_likely_ready(self):
        weak = validate_for_marketplace(_weak_passport())
        strong = validate_for_marketplace(_strong_passport())
        self.assertGreaterEqual(strong.score, weak.score)


if __name__ == "__main__":
    unittest.main()
