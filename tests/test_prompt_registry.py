"""Tests for the Content Pipeline Prompt Registry."""

from __future__ import annotations

import unittest

from app.content_pipeline.prompt_registry import PromptNotFoundError, get_prompt


class PromptRegistryTests(unittest.TestCase):
    def test_universal_fallback_resolves(self):
        spec = get_prompt("title_generator", marketplace="wildberries")
        self.assertEqual(spec.id, "title_generator")
        self.assertEqual(spec.marketplace, "universal")

    def test_unknown_prompt_id_raises(self):
        with self.assertRaises(PromptNotFoundError):
            get_prompt("does_not_exist")

    def test_all_registered_prompts_resolve_schemas(self):
        for prompt_id in (
            "content_strategy_builder",
            "title_generator",
            "benefits_generator",
            "description_generator",
        ):
            spec = get_prompt(prompt_id)
            self.assertTrue(spec.system_prompt.strip())
            self.assertTrue(spec.user_prompt_template.strip())
            input_schema = spec.resolve_input_schema()
            output_schema = spec.resolve_output_schema()
            self.assertTrue(hasattr(input_schema, "model_fields"))
            self.assertTrue(hasattr(output_schema, "model_fields"))

    def test_render_user_prompt_substitutes_context(self):
        spec = get_prompt("content_strategy_builder")
        rendered = spec.render_user_prompt(
            title="Термокружка",
            brand="Stanley",
            category="Посуда",
            price=2990,
            marketplace="ozon",
            attributes={},
            tags=[],
            description="",
        )
        self.assertIn("Термокружка", rendered)
        self.assertIn("Stanley", rendered)


if __name__ == "__main__":
    unittest.main()
