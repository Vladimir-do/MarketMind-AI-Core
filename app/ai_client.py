import json
import os
import ssl
from typing import Any

import aiohttp
import httpx

from app.config import (
    AI_ENABLED,
    AI_PROVIDER,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROK_API_KEY,
    GROQ_API_KEY,
    logger,
)

DEFAULT_SYSTEM_PROMPT = (
    "Ты эксперт по анализу цен на маркетплейсах. "
    "Отвечай кратко, по делу, на русском языке."
)

_aiohttp_session: aiohttp.ClientSession | None = None
_anthropic_client: Any = None
_anthropic_client_config: tuple[str, str | None] | None = None


class AIClientError(RuntimeError):
    """A provider request failed and did not produce usable AI content."""


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


async def _get_aiohttp_session() -> aiohttp.ClientSession:
    global _aiohttp_session
    if _aiohttp_session is None or getattr(_aiohttp_session, "closed", False):
        _aiohttp_session = aiohttp.ClientSession()
    return _aiohttp_session


async def _get_anthropic_client() -> Any:
    global _anthropic_client, _anthropic_client_config
    config = (ANTHROPIC_API_KEY, _resolve_ai_proxy())
    if _anthropic_client is not None and _anthropic_client_config == config:
        return _anthropic_client

    await _close_anthropic_client()
    import anthropic

    http_client = httpx.AsyncClient(proxy=config[1], trust_env=False)
    try:
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            http_client=http_client,
        )
        _anthropic_client_config = config
    except Exception:
        await http_client.aclose()
        raise
    return _anthropic_client


async def _close_anthropic_client() -> None:
    global _anthropic_client, _anthropic_client_config
    client = _anthropic_client
    _anthropic_client = None
    _anthropic_client_config = None
    if client is not None:
        try:
            await client.close()
        except Exception:
            logger.warning("Failed to close Anthropic client", exc_info=True)


async def close_ai_clients() -> None:
    """Close lazily initialized provider clients during application shutdown."""
    global _aiohttp_session
    session = _aiohttp_session
    _aiohttp_session = None
    if session is not None and not getattr(session, "closed", False):
        try:
            close = getattr(session, "close", None)
            if close is not None:
                await close()
        except Exception:
            logger.warning("Failed to close AI aiohttp session", exc_info=True)
    await _close_anthropic_client()


def ai_is_available() -> bool:
    if not AI_ENABLED:
        return False
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        return bool(ANTHROPIC_API_KEY)
    if provider == "grok":
        return bool(GROK_API_KEY)
    if provider == "gemini":
        return bool(GEMINI_API_KEY)
    if provider == "groq":
        return bool(GROQ_API_KEY)
    return bool(GROQ_API_KEY or GROK_API_KEY or ANTHROPIC_API_KEY or GEMINI_API_KEY)


def ai_missing_message() -> str:
    if not AI_ENABLED:
        return "AI недоступен: задайте AI_ENABLED=true в .env для включения AI-слоя"
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        return "AI недоступен: добавьте ANTHROPIC_API_KEY в .env"
    if provider == "grok":
        return "AI недоступен: добавьте GROK_API_KEY в .env"
    if provider == "gemini":
        return "AI недоступен: добавьте GEMINI_API_KEY в .env"
    if provider == "groq":
        return "AI недоступен: добавьте GROQ_API_KEY в .env"
    return "AI недоступен: задайте AI_PROVIDER=groq/grok/claude/gemini и соответствующий ключ"


async def ask_ai(
    prompt: str,
    *,
    system: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 800,
) -> str:
    if not AI_ENABLED:
        raise AIClientError(ai_missing_message())
    if not ai_is_available():
        raise AIClientError(ai_missing_message())
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        response = await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    elif provider == "grok":
        response = await _ask_grok(prompt, system=system, max_tokens=max_tokens)
    elif provider == "gemini":
        response = await _ask_gemini(prompt, system=system, max_tokens=max_tokens)
    elif provider == "groq":
        response = await _ask_groq(prompt, system=system, max_tokens=max_tokens)
    elif GROQ_API_KEY:
        response = await _ask_groq(prompt, system=system, max_tokens=max_tokens)
    elif GROK_API_KEY:
        response = await _ask_grok(prompt, system=system, max_tokens=max_tokens)
    elif ANTHROPIC_API_KEY:
        response = await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    elif GEMINI_API_KEY:
        response = await _ask_gemini(prompt, system=system, max_tokens=max_tokens)
    else:
        return ai_missing_message()

    if response.startswith("AI error:"):
        raise AIClientError(response.removeprefix("AI error:").strip())
    return response


async def _ask_claude(prompt: str, *, system: str, max_tokens: int) -> str:
    if not ANTHROPIC_API_KEY:
        return ai_missing_message()
    try:
        client = await _get_anthropic_client()
        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error("Claude API error: %r", e, exc_info=True)
        return f"AI error: {type(e).__name__}: {e}" if str(e) else f"AI error: {type(e).__name__}"


async def _ask_grok(prompt: str, *, system: str, max_tokens: int) -> str:
    if not GROK_API_KEY:
        return ai_missing_message()
    try:
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "grok-3-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        session = await _get_aiohttp_session()
        async with session.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                message = None
                if isinstance(data, dict):
                    error = data.get("error")
                    if isinstance(error, dict):
                        message = error.get("message")
                    elif isinstance(error, str):
                        message = error
                return f"AI error: {message or resp.status}"
            if not isinstance(data, dict):
                return f"AI error: unexpected response type {type(data).__name__}"
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("Grok API error: %r", e, exc_info=True)
        return f"AI error: {type(e).__name__}: {e}" if str(e) else f"AI error: {type(e).__name__}"


async def _ask_groq(prompt: str, *, system: str, max_tokens: int) -> str:
    if not GROQ_API_KEY:
        return ai_missing_message()
    proxy_url = _resolve_ai_proxy()
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        session = await _get_aiohttp_session()
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
            proxy=proxy_url,
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                message = None
                if isinstance(data, dict):
                    error = data.get("error")
                    if isinstance(error, dict):
                        message = error.get("message")
                    elif isinstance(error, str):
                        message = error
                return f"AI error: {message or resp.status}"
            if not isinstance(data, dict):
                return f"AI error: unexpected response type {type(data).__name__}"
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("Groq API error: %r", e, exc_info=True)
        return f"AI error: {type(e).__name__}: {e}" if str(e) else f"AI error: {type(e).__name__}"


async def _ask_gemini(prompt: str, *, system: str, max_tokens: int) -> str:
    if not GEMINI_API_KEY:
        return ai_missing_message()
    try:
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system}\n\n{prompt}"}]},
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.3,
                "responseMimeType": "application/json" if "required_json_schema" in prompt else "text/plain",
            },
        }
        headers["x-goog-api-key"] = GEMINI_API_KEY
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{GEMINI_MODEL}:generateContent"
        )
        proxy_url = _resolve_ai_proxy()
        session = await _get_aiohttp_session()
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
            proxy=proxy_url,
        ) as resp:
            body_text = await resp.text()
            data = _safe_json_loads(body_text)
            if resp.status >= 400:
                return _gemini_http_error_message(resp.status, data, body_text, resp)
            if not isinstance(data, dict):
                return f"AI error: unexpected response type {type(data).__name__}"
            candidates = data.get("candidates", [])
            if not candidates:
                return "AI error: no candidates in response"
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return "AI error: no parts in response"
            return parts[0].get("text", "")
    except TimeoutError as e:
        logger.error("Gemini API timeout: %r", e, exc_info=True)
        return _gemini_timeout_message(e)
    except Exception as e:
        logger.error("Gemini API error: %r", e, exc_info=True)
        return _gemini_exception_message(e)


def _safe_json_loads(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _gemini_http_error_message(status: int, data: object, body_text: str, resp: object | None = None) -> str:
    error_message = _gemini_error_message_from_body(data)
    retry_after = ""
    if resp is not None:
        raw_retry = getattr(resp, "headers", {}).get("Retry-After", "")
        if raw_retry:
            retry_after = f" retry_after={raw_retry}"
    logger.warning(
        "Gemini HTTP error status=%s message=%s%s body=%s",
        status,
        error_message or "unknown",
        retry_after,
        _safe_body_snippet(body_text),
    )

    if status == 401 or status == 403:
        return f"AI error: Gemini API недоступен: проверьте API-ключ или права доступа (HTTP {status})"
    if status == 404:
        return "AI error: Gemini API недоступен: неверная модель или endpoint (HTTP 404)"
    if status == 429:
        return (
            "AI error: Gemini API недоступен: для текущего API-ключа отсутствует доступная квота "
            "или превышен лимит запросов. Проверьте тариф и лимиты Google AI Studio (HTTP 429)"
        )
    if 500 <= status <= 599:
        return f"AI error: Gemini API временно недоступен (HTTP {status})"
    return f"AI error: Gemini API error (HTTP {status})"


def _gemini_error_message_from_body(data: object) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        if isinstance(error, str):
            return error
    return ""


def _safe_body_snippet(body_text: str, limit: int = 500) -> str:
    snippet = body_text
    if GEMINI_API_KEY:
        snippet = snippet.replace(GEMINI_API_KEY, "<redacted>")
    return snippet[:limit]


def _gemini_timeout_message(exc: Exception) -> str:
    server_timeout_error = getattr(aiohttp, "ServerTimeoutError", None)
    connection_timeout_error = getattr(aiohttp, "ConnectionTimeoutError", None)
    if connection_timeout_error is not None and isinstance(exc, connection_timeout_error):
        return "AI error: Gemini connection timeout"
    if server_timeout_error is not None and isinstance(exc, server_timeout_error):
        return "AI error: Gemini read timeout"
    return "AI error: Gemini request timeout"


def _gemini_exception_message(exc: Exception) -> str:
    server_timeout_error = getattr(aiohttp, "ServerTimeoutError", None)
    connection_timeout_error = getattr(aiohttp, "ConnectionTimeoutError", None)
    if connection_timeout_error is not None and isinstance(exc, connection_timeout_error):
        return "AI error: Gemini connection timeout"
    if server_timeout_error is not None and isinstance(exc, server_timeout_error):
        return "AI error: Gemini read timeout"
    if isinstance(exc, aiohttp.ClientConnectorCertificateError):
        return "AI error: Gemini SSL/TLS error"
    if isinstance(exc, aiohttp.ClientSSLError):
        return "AI error: Gemini SSL/TLS error"
    if isinstance(exc, ssl.SSLError):
        return "AI error: Gemini SSL/TLS error"
    if isinstance(exc, aiohttp.ClientConnectorError):
        return "AI error: Gemini connection error"
    if isinstance(exc, TimeoutError):
        return "AI error: Gemini request timeout"
    return f"AI error: {type(exc).__name__}: {exc}" if str(exc) else f"AI error: {type(exc).__name__}"
