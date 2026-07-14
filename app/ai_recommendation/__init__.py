"""AI Recommendation Layer — optional AI-powered product improvement suggestions."""

from app.ai_recommendation.approval import ApprovalQueue, PendingApproval
from app.ai_recommendation.engine import AIRecommendationEngine
from app.ai_recommendation.layer import AIRecommendationLayer, AIResult
from app.ai_recommendation.mock_provider import MockAIProvider
from app.ai_recommendation.provider import AIProvider, AIResponse
from app.ai_recommendation.suggestions import (
    AIBatchRecommendationResult,
    AIRecommendationResult,
    AISuggestion,
)

__all__ = [
    "AIProvider",
    "AIResponse",
    "AISuggestion",
    "AIRecommendationResult",
    "AIBatchRecommendationResult",
    "AIRecommendationEngine",
    "AIRecommendationLayer",
    "AIResult",
    "MockAIProvider",
    "PendingApproval",
    "ApprovalQueue",
]
