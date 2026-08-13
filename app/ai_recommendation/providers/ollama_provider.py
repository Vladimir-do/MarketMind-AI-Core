"""Ollama local provider — no API key required."""

from __future__ import annotations

import logging
import time

import aiohttp

from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.providers.base import BaseAIProvider

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(BaseAIProvider):
    """Provider that talks to a local Ollama instance via /api/chat."""

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "",
        timeout: float = 120.0,
    ) -> None:
        resolved_url = base_url or _DEFAULT_BASE_URL
        super().__init__(api_key="", model=model, base_url=resolved_url, timeout=timeout)

    def is_available(self) -> bool:
        return bool(self._base_url)

    def name(self) -> str:
        return "ollama"

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        url = f"{self._base_url}/api/chat"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        start = time.monotonic()
        try:
            timeout_obj = aiohttp.ClientTimeout(total=self._timeout)
            async with (
                aiohttp.ClientSession(timeout=timeout_obj) as session,
                session.post(url, json=payload) as resp,
            ):
                body = await resp.json()
                if resp.status != 200:
                    error_msg = body.get("error", str(body))
                    raise RuntimeError(f"Ollama HTTP {resp.status}: {error_msg}")
                content = body.get("message", {}).get("content", "")
                return AIResponse(
                    text=content,
                    model=body.get("model", self._model),
                    input_tokens=body.get("prompt_eval_count", 0),
                    output_tokens=body.get("eval_count", 0),
                    latency_ms=self._elapsed_ms(start),
                )
        except Exception as exc:
            return self._create_error_response(exc, prompt)
