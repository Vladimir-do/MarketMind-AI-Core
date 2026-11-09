"""OpenAI-compatible provider — OpenAI, DeepSeek, MiMo and compatible APIs."""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
from typing import Any

import aiohttp
from aiohttp import (
    ClientConnectorCertificateError,
    ClientConnectorError,
    ClientError,
    ClientSSLError,
    ServerTimeoutError,
)

from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.providers.base import BaseAIProvider

logger = logging.getLogger(__name__)


def _resolve_ai_proxy() -> str | None:
    configured_proxy = os.environ.get("AI_HTTP_PROXY", "").strip()
    if configured_proxy:
        if configured_proxy.lower() in {"direct", "none", "off"}:
            return None
        return configured_proxy
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key, "").strip()
        if value and value.lower() not in {"direct", "none", "off"}:
            return value
    return None


_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.mimo.ai/v1",
}


class ProviderHTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class OpenAICompatibleProvider(BaseAIProvider):
    """Provider that speaks the OpenAI chat-completions protocol."""

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

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

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
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        start = time.monotonic()
        logger.info(
            "AI request provider=%s model=%s url=%s timeout_s=%s stage=request_started",
            self.name(), self._model, url, self._timeout,
        )
        try:
            timeout_obj = aiohttp.ClientTimeout(total=self._timeout, connect=min(self._timeout, 20.0))
            # aiohttp does not read proxy environment variables by default.
            # MarketMind runs behind HAPP on this host, so route provider
            # requests through the explicitly configured AI proxy.
            proxy_url = _resolve_ai_proxy()
            async with (
                aiohttp.ClientSession(timeout=timeout_obj) as session,
                session.post(url, json=payload, headers=headers, proxy=proxy_url) as resp,
            ):
                try:
                    body = await resp.json(content_type=None)
                    raw = json.dumps(body, ensure_ascii=False)
                except Exception:
                    raw = await resp.text()
                    body = _safe_json(raw)
                if resp.status < 200 or resp.status >= 300:
                    raise ProviderHTTPError(resp.status, _extract_error(body, raw))
                if not isinstance(body, dict):
                    raise ValueError(f"Unexpected response type: {type(body).__name__}")
                choices = body.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise ValueError("Response has no choices")
                message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                content = message.get("content", "") if isinstance(message, dict) else ""
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Response content is empty")
                usage = body.get("usage", {}) if isinstance(body.get("usage", {}), dict) else {}
                result = AIResponse(
                    text=content,
                    model=str(body.get("model") or self._model),
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or 0),
                    latency_ms=self._elapsed_ms(start),
                )
                logger.info(
                    "AI response provider=%s model=%s status=%s latency_ms=%s input_tokens=%s output_tokens=%s stage=response_received",
                    self.name(), result.model, resp.status, result.latency_ms, result.input_tokens, result.output_tokens,
                )
                return result
        except ProviderHTTPError as exc:
            return self._create_error_response(exc, prompt, started_at=start, status_code=exc.status, stage="http")
        except (TimeoutError, ServerTimeoutError) as exc:
            return self._create_error_response(exc, prompt, started_at=start, stage=_timeout_stage(exc))
        except (ClientConnectorCertificateError, ClientSSLError, ssl.SSLError) as exc:
            return self._create_error_response(exc, prompt, started_at=start, stage="ssl")
        except ClientConnectorError as exc:
            return self._create_error_response(exc, prompt, started_at=start, stage="connect")
        except ClientError as exc:
            return self._create_error_response(exc, prompt, started_at=start, stage="network")
        except Exception as exc:
            return self._create_error_response(exc, prompt, started_at=start, stage="parse")


def _safe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _extract_error(body: Any, raw: str) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or error)
        if error:
            return str(error)
        message = body.get("message")
        if message:
            return str(message)
    compact = " ".join(raw.split())
    return compact[:500] or "empty error response"


def _timeout_stage(exc: BaseException) -> str:
    connection_timeout = getattr(aiohttp, "ConnectionTimeoutError", None)
    if connection_timeout is not None and isinstance(exc, connection_timeout):
        return "connect_timeout"
    socket_timeout = getattr(aiohttp, "SocketTimeoutError", None)
    if socket_timeout is not None and isinstance(exc, socket_timeout):
        return "read_timeout"
    return "request_timeout"
