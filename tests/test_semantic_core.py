"""Тесты модуля Semantic Core."""

import unittest

from app.semantic_core import SemanticCore, build_semantic_core, semantic_coverage_findings
from app.seo_rules import SEOMarketplaceRule


class TestBuildSemanticCore(unittest.TestCase):
    """Тесты функции build_semantic_core."""

    def test_full_product_data(self):
        """Товар с полными данными — высокий coverage, есть primary."""
        core = build_semantic_core(
            name="Магний цитрат в таблетках",
            description="Минеральная добавка для здоровья.",
            attributes={"Форма": "таблетки", "Дозировка": "200 мг"},
            category="Витамины и БАДы",
            tags=["магний", "цитрат", "минерал", "таблетки", "добавка", "здоровье"],
            brand="Nature Made",
        )
        self.assertGreater(core.coverage_score, 0.0)
        self.assertGreater(len(core.primary_terms), 0)
        self.assertGreater(core.total_terms, 0)

    def test_empty_name(self):
        """Товар без названия — нет primary terms."""
        core = build_semantic_core(
            name=None,
            description="Описание товара",
            attributes=None,
            category=None,
            tags=None,
            brand=None,
        )
        self.assertEqual(core.primary_terms, [])

    def test_junk_ratio_high(self):
        """Товар с мусорными словами — высокий junk ratio."""
        rules = SEOMarketplaceRule(
            marketplace_name="test",
            forbidden_words=frozenset({"купить", "дешево", "скидка"}),
        )
        core = build_semantic_core(
            name="Кабель USB-C",
            description="",
            attributes=None,
            category=None,
            tags=["купить", "дешево", "скидка", "кабель"],
            brand=None,
            rules=rules,
        )
        self.assertGreater(core.junk_ratio, 0.0)
        self.assertIn("купить", core.forbidden_terms)
        self.assertIn("дешево", core.forbidden_terms)
        self.assertIn("скидка", core.forbidden_terms)

    def test_attribute_terms(self):
        """Товар с атрибутами — attribute terms извлечены."""
        core = build_semantic_core(
            name="Кабель USB-C",
            description=None,
            attributes={"Материал": "нейлон", "Длина": "2 метра", "Цвет": "чёрный"},
            category=None,
            tags=None,
            brand=None,
        )
        self.assertIn("нейлон", core.attribute_terms)
        self.assertIn("метра", core.attribute_terms)

    def test_category_terms(self):
        """Товар с category — category terms извлечены."""
        core = build_semantic_core(
            name="Кабель USB-C",
            description=None,
            attributes=None,
            category="Кабели и провода",
            tags=None,
            brand=None,
        )
        self.assertIn("кабели", core.category_terms)
        self.assertIn("провода", core.category_terms)

    def test_forbidden_words_filtered(self):
        """Forbidden words отфильтрованы из полезных терминов."""
        rules = SEOMarketplaceRule(
            marketplace_name="test",
            forbidden_words=frozenset({"акция", "скидка"}),
        )
        core = build_semantic_core(
            name="Наушники Bluetooth",
            description=None,
            attributes=None,
            category=None,
            tags=["акция", "скидка", "наушники"],
            brand=None,
            rules=rules,
        )
        self.assertIn("акция", core.forbidden_terms)
        self.assertIn("скидка", core.forbidden_terms)
        self.assertNotIn("акция", core.secondary_terms)
        self.assertNotIn("акция", core.long_tail_terms)

    def test_noisy_terms(self):
        """Артикулы (AB123) отфильтрованы как noisy."""
        core = build_semantic_core(
            name="Кабель USB-C AB123",
            description=None,
            attributes=None,
            category=None,
            tags=None,
            brand=None,
        )
        # AB123 -> ab123, which matches [A-Z]{2,}\d{3,} pattern
        self.assertIn("ab123", core.noisy_terms)

    def test_brand_terms(self):
        """Brand terms извлечены."""
        core = build_semantic_core(
            name="Кабель Xiaomi USB-C",
            description=None,
            attributes=None,
            category=None,
            tags=None,
            brand="Xiaomi",
        )
        self.assertIn("xiaomi", core.brand_terms)

    def test_coverage_findings(self):
        """semantic_coverage_findings возвращает находки."""
        core = SemanticCore(
            primary_terms=[],
            secondary_terms=[],
            long_tail_terms=[],
            brand_terms=[],
            attribute_terms=[],
            category_terms=[],
            forbidden_terms=[],
            noisy_terms=[],
            total_terms=0,
            coverage_score=0.0,
            junk_ratio=0.0,
        )
        findings = semantic_coverage_findings(core)
        rules_ids = [f.rule for f in findings]
        self.assertIn("seo_semantic_no_primary", rules_ids)
        self.assertIn("seo_semantic_few_secondary", rules_ids)
        self.assertIn("seo_semantic_low_coverage", rules_ids)

    def test_all_fields_none(self):
        """Edge case — все поля None."""
        core = build_semantic_core(
            name=None,
            description=None,
            attributes=None,
            category=None,
            tags=None,
            brand=None,
        )
        self.assertEqual(core.primary_terms, [])
        self.assertEqual(core.secondary_terms, [])
        self.assertEqual(core.long_tail_terms, [])
        self.assertEqual(core.brand_terms, [])
        self.assertEqual(core.attribute_terms, [])
        self.assertEqual(core.category_terms, [])
        self.assertEqual(core.total_terms, 0)
        self.assertEqual(core.coverage_score, 0.0)
        self.assertEqual(core.junk_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
