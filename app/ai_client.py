import aiohttp

from app.config import AI_PROVIDER, ANTHROPIC_API_KEY, GROK_API_KEY, logger


DEFAULT_SYSTEM_PROMPT = (
    "Ты эксперт по анализу цен на маркетплейсах. "
    "Отвечай кратко, по делу, на русском языке."
)


def ai_is_available() -> bool:
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        return bool(ANTHROPIC_API_KEY)
    if provider == "grok":
        return bool(GROK_API_KEY)
    return bool(GROK_API_KEY or ANTHROPIC_API_KEY)


def ai_missing_message() -> str:
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        return "AI недоступен: добавьте ANTHROPIC_API_KEY в .env"
    if provider == "grok":
        return "AI недоступен: добавьте GROK_API_KEY в .env"
    return "AI недоступен: задайте AI_PROVIDER=grok или AI_PROVIDER=claude и соответствующий ключ"


async def ask_ai(
    prompt: str,
    *,
    system: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 800,
) -> str:
    provider = AI_PROVIDER.strip().lower()
    if provider == "claude":
        return await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    if provider == "grok":
        return await _ask_grok(prompt, system=system, max_tokens=max_tokens)

    if GROK_API_KEY:
        return await _ask_grok(prompt, system=system, max_tokens=max_tokens)
    if ANTHROPIC_API_KEY:
        return await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    return ai_missing_message()


async def _ask_claude(prompt: str, *, system: str, max_tokens: int) -> str:
    if not ANTHROPIC_API_KEY:
        return ai_missing_message()
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return f"AI error: {e}"


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
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                "https://api.x.ai/v1/chat/completions",
                json=payload,
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
        logger.error(f"Grok API error: {e}")
        return f"AI error: {e}"
