"""Fallback provider — tries providers in order until one succeeds."""

from __future__ import annotations

import logging

from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.providers.base import BaseAIProvider

logger = logging.getLogger(__name__)


class FallbackAIProvider(BaseAIProvider):
    """Wraps a list of providers and tries them sequentially."""

    def __init__(self, providers: list[BaseAIProvider]) -> None:
        super().__init__()
        self._providers = providers

    def is_available(self) -> bool:
        return any(p.is_available() for p in self._providers)

    def name(self) -> str:
        available = [p.name() for p in self._providers if p.is_available()]
        return "fallback[" + "|".join(available) + "]" if available else "fallback[none]"

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            if not provider.is_available():
                logger.debug("[fallback] skipping unavailable provider: %s", provider.name())
                continue
            try:
                result = await provider.complete(prompt, system, max_tokens, temperature)
                if result.text:
                    return result
                logger.warning("[fallback] %s returned empty response, trying next", provider.name())
            except Exception as exc:
                last_error = exc
                logger.warning("[fallback] %s failed: %s, trying next", provider.name(), exc)

        return self._create_error_response(
            last_error or RuntimeError("All providers unavailable"),
            prompt,
        )
