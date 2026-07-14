"""Abstract base class for AI providers."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from app.ai_recommendation.provider import AIResponse

logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """Base class all real AI providers inherit from."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def is_available(self) -> bool:
        return bool(self._api_key or self._base_url)

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        ...

    @abstractmethod
    def name(self) -> str:
        ...

    def _create_error_response(self, error: Exception, prompt: str) -> AIResponse:
        logger.error("[%s] API call failed: %s", self.name(), error)
        return AIResponse(
            text="",
            model=self._model,
            latency_ms=0.0,
        )

    def _elapsed_ms(self, start: float) -> float:
        return round((time.monotonic() - start) * 1000, 1)
