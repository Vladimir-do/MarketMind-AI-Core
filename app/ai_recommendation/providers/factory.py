"""Provider factory — creates providers from config or explicit parameters."""

from __future__ import annotations

import enum
import logging
import os

from app.ai_recommendation.providers.base import BaseAIProvider
from app.ai_recommendation.providers.ollama_provider import OllamaProvider
from app.ai_recommendation.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class ProviderType(enum.Enum):
    openai = "openai"
    deepseek = "deepseek"
    mimo = "mimo"
    ollama = "ollama"
    claude = "claude"
    grok = "grok"
    gemini = "gemini"


_PROVIDER_MODELS: dict[ProviderType, str] = {
    ProviderType.openai: "gpt-4o-mini",
    ProviderType.deepseek: "deepseek-chat",
    ProviderType.mimo: "mimo-auto",
    ProviderType.ollama: "llama3",
    ProviderType.claude: "claude-3-haiku-20240307",
    ProviderType.grok: "grok-1",
    ProviderType.gemini: "gemini-1.5-flash",
}

_PROVIDER_KEYS: dict[ProviderType, str] = {
    ProviderType.openai: "OPENAI_API_KEY",
    ProviderType.deepseek: "DEEPSEEK_API_KEY",
    ProviderType.mimo: "MIMO_API_KEY",
    ProviderType.claude: "ANTHROPIC_API_KEY",
    ProviderType.grok: "GROK_API_KEY",
    ProviderType.gemini: "GEMINI_API_KEY",
}

_PROVIDER_BASE_URLS: dict[ProviderType, str] = {
    ProviderType.grok: "https://api.x.ai/v1",
    ProviderType.gemini: "https://generativelanguage.googleapis.com/v1beta/openai",
}


def create_provider(provider_type: ProviderType, **kwargs) -> BaseAIProvider:
    """Create a provider by type.  Keyword args override defaults."""
    if provider_type is ProviderType.ollama:
        return OllamaProvider(
            model=kwargs.get("model", _PROVIDER_MODELS[ProviderType.ollama]),
            base_url=kwargs.get("base_url", os.getenv("OLLAMA_BASE_URL", "")),
            timeout=kwargs.get("timeout", 120.0),
        )

    # OpenAI-compatible: openai, deepseek, mimo, claude, grok, gemini
    api_key = kwargs.get("api_key", "")
    if not api_key:
        env_key = _PROVIDER_KEYS.get(provider_type, "")
        api_key = os.getenv(env_key, "") if env_key else ""

    return OpenAICompatibleProvider(
        api_key=api_key,
        model=kwargs.get("model", _PROVIDER_MODELS.get(provider_type, "")),
        base_url=kwargs.get("base_url", _PROVIDER_BASE_URLS.get(provider_type, "")),
        provider_label=provider_type.value,
        timeout=kwargs.get("timeout", 60.0),
    )


def create_configured_provider() -> BaseAIProvider:
    """Create the provider specified by AI_PROVIDER env var."""
    raw = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    try:
        ptype = ProviderType(raw)
    except ValueError:
        logger.warning("Unknown AI_PROVIDER=%s, falling back to ollama", raw)
        ptype = ProviderType.ollama

    model_env_map: dict[str, str] = {
        "openai": "OPENAI_MODEL",
        "deepseek": "DEEPSEEK_MODEL",
        "mimo": "MIMO_MODEL",
        "ollama": "OLLAMA_MODEL",
    }
    model_env = model_env_map.get(ptype.value, "")
    model = os.getenv(model_env, "") if model_env else ""

    kwargs: dict[str, object] = {}
    if model:
        kwargs["model"] = model

    return create_provider(ptype, **kwargs)
