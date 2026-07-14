"""Mock AI provider for testing and development."""

from __future__ import annotations

import json

from app.ai_recommendation.provider import AIResponse


class MockAIProvider:
    """Returns deterministic suggestions without calling any API."""

    def __init__(self, model: str = "mock-v1") -> None:
        self._model = model

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        suggestions = self._default_suggestions()
        return AIResponse(
            text=json.dumps(suggestions, ensure_ascii=False),
            model=self._model,
            input_tokens=len(prompt.split()),
            output_tokens=len(json.dumps(suggestions).split()),
            latency_ms=1.0,
        )

    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "mock"

    @staticmethod
    def _default_suggestions() -> list[dict[str, str]]:
        return [
            {
                "field": "name",
                "suggestion_type": "improve",
                "before": "",
                "after": "Улучшенное название с ключевыми словами",
                "reason": "Название слишком короткое и не содержит ключевых слов для поиска",
                "confidence": "0.85",
                "source_finding": "name_too_short",
            },
            {
                "field": "description",
                "suggestion_type": "expand",
                "before": "",
                "after": "Развёрнутое описание с характеристиками и преимуществами товара",
                "reason": "Описание отсутствует или слишком краткое для принятия решения о покупке",
                "confidence": "0.78",
                "source_finding": "description_missing",
            },
        ]
