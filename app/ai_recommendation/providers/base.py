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
    ) -> AIResponse: ...

    @abstractmethod
    def name(self) -> str: ...

    def _create_error_response(
        self,
        error: Exception,
        prompt: str,
        *,
        started_at: float | None = None,
        status_code: int | None = None,
        stage: str = "request",
    ) -> AIResponse:
        latency_ms = self._elapsed_ms(started_at) if started_at is not None else 0.0
        error_type = type(error).__name__
        error_message = str(error) or error_type
        logger.error(
            "[%s] API call failed model=%s stage=%s status=%s latency_ms=%s error_type=%s error=%s",
            self.name(),
            self._model,
            stage,
            status_code,
            latency_ms,
            error_type,
            error_message,
            exc_info=True,
        )
        return AIResponse(
            text="",
            model=self._model,
            latency_ms=latency_ms,
            error_type=error_type,
            error_message=error_message,
            status_code=status_code,
            error_stage=stage,
        )

    def _elapsed_ms(self, start: float) -> float:
        return round((time.monotonic() - start) * 1000, 1)
