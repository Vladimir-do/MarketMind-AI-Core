"""Real AI providers for the recommendation engine."""

from app.ai_recommendation.providers.base import BaseAIProvider
from app.ai_recommendation.providers.factory import (
    ProviderType,
    create_configured_provider,
    create_provider,
)
from app.ai_recommendation.providers.fallback import FallbackAIProvider
from app.ai_recommendation.providers.ollama_provider import OllamaProvider
from app.ai_recommendation.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "BaseAIProvider",
    "OpenAICompatibleProvider",
    "OllamaProvider",
    "FallbackAIProvider",
    "ProviderType",
    "create_provider",
    "create_configured_provider",
]
