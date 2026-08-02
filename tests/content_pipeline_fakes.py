"""Скриптуемый fake AI-провайдер для тестов Content Pipeline.

В отличие от MockAIProvider (app/ai_recommendation/mock_provider.py),
который всегда отдаёт один и тот же фиксированный ответ, этот провайдер
отдаёт заранее заданную очередь ответов — по одному на каждый вызов
complete(), что нужно для тестирования многостадийного пайплайна.
"""

from __future__ import annotations

from app.ai_recommendation.provider import AIResponse


class ScriptedAIProvider:
    def __init__(self, responses: list[str], *, model: str = "scripted-v1") -> None:
        self._queue = list(responses)
        self._model = model
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        self.calls.append({"prompt": prompt, "system": system})
        if not self._queue:
            raise AssertionError("ScriptedAIProvider queue exhausted — not enough scripted responses")
        text = self._queue.pop(0)
        return AIResponse(text=text, model=self._model, latency_ms=1.0)

    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "scripted"
