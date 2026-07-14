"""Suggestion and result data structures for AI recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AISuggestion:
    """A single AI-generated improvement suggestion."""

    field: str
    suggestion_type: str  # improve | expand | add | fix | optimize
    before: str
    after: str
    reason: str
    confidence: float  # 0.0–1.0
    source_finding: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIRecommendationResult:
    """AI recommendations for a single product."""

    product_id: str
    suggestions: list[AISuggestion] = field(default_factory=list)
    summary: str = ""
    overall_confidence: float = 0.0
    model_used: str = ""
    tokens_used: int = 0


@dataclass
class AIBatchRecommendationResult:
    """Aggregated AI recommendations across multiple products."""

    results: list[AIRecommendationResult] = field(default_factory=list)
    total_suggestions: int = 0
    high_confidence_count: int = 0
    model_used: str = ""
