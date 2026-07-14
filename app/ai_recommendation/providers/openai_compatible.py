"""OpenAI-compatible provider — works for OpenAI, DeepSeek, MiMo, and any compatible API."""

from __future__ import annotations

import json
import logging
import time

import aiohttp

from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.providers.base import BaseAIProvider

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.mimo.ai/v1",
}


class OpenAICompatibleProvider(BaseAIProvider):
    """Provider that speaks the OpenAI chat completions protocol."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str = "",
        provider_label: str = "openai",
        timeout: float = 60.0,
    ) -> None:
        resolved_url = base_url or _DEFAULT_BASE_URLS.get(provider_label, "")
        super().__init__(api_key=api_key, model=model, base_url=resolved_url, timeout=timeout)
        self._label = provider_label

    def is_available(self) -> bool:
        return bool(self._api_key and self._base_url)

    def name(self) -> str:
        return self._label

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        url = f"{self._base_url}/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start = time.monotonic()
        try:
            timeout_obj = aiohttp.ClientTimeout(total=self._timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    body = await resp.json()
                    if resp.status != 200:
                        error_msg = body.get("error", {}).get("message", str(body))
                        raise RuntimeError(f"HTTP {resp.status}: {error_msg}")
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage", {})
                    return AIResponse(
                        text=content,
                        model=body.get("model", self._model),
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        latency_ms=self._elapsed_ms(start),
                    )
        except Exception as exc:
            return self._create_error_response(exc, prompt)
