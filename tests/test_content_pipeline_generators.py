"""Tests for the LLM-backed generator stages (strategy/title/benefits/description)."""

from __future__ import annotations

import json
import unittest

from app.content_pipeline.benefits_generator import generate_benefits
from app.content_pipeline.description_generator import generate_description
from app.content_pipeline.parsing import ContentPipelineParseError
from app.content_pipeline.schemas import BenefitsGenerationResult, ContentStrategy, ProductPassport, SemanticPlan
from app.content_pipeline.strategy_builder import build_content_strategy
from app.content_pipeline.title_generator import generate_title
from tests.content_pipeline_fakes import ScriptedAIProvider

_PASSPORT = ProductPassport(
    product_id=1,
    project_id="proj-1",
    project_product_id="pp-1",
    title="Термокружка Stanley 500 мл",
    brand="Stanley",
    category="Термокружки",
    marketplace="ozon",
    attributes={"Материал": "Сталь", "Объём": "500 мл"},
)

_STRATEGY = ContentStrategy(
    target_audience="Путешественники",
    key_need="Держать напитки горячими в дороге",
    key_selling_proposition="Держит температуру 12 часов",
    tone_of_voice="уверенный",
)

_SEMANTIC_PLAN = SemanticPlan(
    title_terms=["термокружка", "stanley"], benefits_terms=["сталь"], description_terms=["500мл"]
)


class StrategyBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_valid_response(self):
        payload = {
            "target_audience": "Путешественники",
            "usage_scenarios": ["в дороге"],
            "key_need": "Тепло",
            "key_selling_proposition": "Держит температуру 12 часов",
            "secondary_benefits": [],
            "objections": [],
            "objection_responses": [],
            "tone_of_voice": "уверенный",
            "description_structure": [],
            "priority_attributes": [],
            "forbidden_claims": [],
            "formality_level": "professional",
        }
        provider = ScriptedAIProvider([json.dumps(payload, ensure_ascii=False)])
        outcome = await build_content_strategy(_PASSPORT, provider)
        self.assertEqual(outcome.result.target_audience, "Путешественники")
        self.assertEqual(outcome.prompt_id, "content_strategy_builder")
        self.assertEqual(outcome.model_used, "scripted-v1")

    async def test_invalid_json_raises_parse_error(self):
        provider = ScriptedAIProvider(["это не json"])
        with self.assertRaises(ContentPipelineParseError):
            await build_content_strategy(_PASSPORT, provider)

    async def test_markdown_fenced_response_is_stripped(self):
        payload = {
            "target_audience": "A",
            "key_need": "B",
            "key_selling_proposition": "C",
            "tone_of_voice": "D",
        }
        fenced = "```json\n" + json.dumps(payload) + "\n```"
        provider = ScriptedAIProvider([fenced])
        outcome = await build_content_strategy(_PASSPORT, provider)
        self.assertEqual(outcome.result.target_audience, "A")


class TitleGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_valid_response(self):
        payload = {
            "title": "Термокружка Stanley 500 мл нержавеющая сталь",
            "alternatives": ["Вариант 2", "Вариант 3", "Вариант 4", "Вариант 5"],
            "used_keywords": ["термокружка", "stanley"],
            "reasoning": "включили primary-термины",
            "confidence": 0.9,
        }
        provider = ScriptedAIProvider([json.dumps(payload, ensure_ascii=False)])
        outcome = await generate_title(_PASSPORT, _STRATEGY, _SEMANTIC_PLAN, provider)
        self.assertEqual(len(outcome.result.alternatives), 4)
        self.assertIn("Stanley", outcome.result.title)

    async def test_provider_error_raises_parse_error(self):
        from app.ai_recommendation.provider import AIResponse

        class BrokenProvider:
            async def complete(self, prompt, system="", max_tokens=2048, temperature=0.3):
                return AIResponse(text="", model="x", error_type="timeout", error_message="boom")

            def is_available(self):
                return True

            def name(self):
                return "broken"

        with self.assertRaises(ContentPipelineParseError):
            await generate_title(_PASSPORT, _STRATEGY, _SEMANTIC_PLAN, BrokenProvider())


class BenefitsGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_valid_response(self):
        payload = {
            "bullets": ["Сталь -> прочность -> не мнётся при падении"],
            "infographic_bullets": ["Прочная сталь"],
            "description_bullets": ["Корпус из стали устойчив к деформации"],
            "objection_counters": [],
            "reasoning": "",
            "confidence": 0.8,
        }
        provider = ScriptedAIProvider([json.dumps(payload, ensure_ascii=False)])
        outcome = await generate_benefits(_PASSPORT, _STRATEGY, _SEMANTIC_PLAN, provider)
        self.assertEqual(len(outcome.result.bullets), 1)


class DescriptionGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_valid_response_using_benefits_context(self):
        benefits = BenefitsGenerationResult(
            bullets=["Сталь -> прочность -> результат"],
            description_bullets=["Корпус из стали устойчив к деформации"],
        )
        payload = {
            "short_description": "Термокружка для тепла в дороге",
            "full_description": "Полное описание термокружки Stanley.",
            "blocks": {"назначение": "путешествия"},
            "used_keywords": ["500мл"],
            "reasoning": "",
            "confidence": 0.85,
        }
        provider = ScriptedAIProvider([json.dumps(payload, ensure_ascii=False)])
        outcome = await generate_description(_PASSPORT, _STRATEGY, _SEMANTIC_PLAN, benefits, provider)
        self.assertEqual(outcome.result.full_description, "Полное описание термокружки Stanley.")
        # benefits context should have been embedded in the rendered prompt sent to the provider
        self.assertIn("Корпус из стали", provider.calls[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
