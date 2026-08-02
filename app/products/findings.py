"""Data structures for product intelligence analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.products.schema import UnifiedProduct


@dataclass(frozen=True)
class Finding:
    """A single issue detected by an analysis rule."""

    rule: str
    field: str
    message: str
    severity: str  # critical | warning | info
    category: str  # completeness | consistency | quality


@dataclass(frozen=True)
class Recommendation:
    """Actionable suggestion derived from a finding."""

    finding: Finding
    action: str
    priority: int  # 1 = highest
    description: str


@dataclass
class AnalysisResult:
    """Per-product analysis output."""

    product: UnifiedProduct
    score: int  # 0-100
    findings: list[Finding] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    tier: str = ""  # excellent / good / fair / poor / critical


@dataclass
class BatchAnalysisResult:
    """Aggregated results across multiple products."""

    total: int
    average_score: float
    score_distribution: dict[str, int] = field(default_factory=dict)
    findings_summary: dict[str, int] = field(default_factory=dict)
    top_recommendations: list[Recommendation] = field(default_factory=list)
    products_below_threshold: list[str] = field(default_factory=list)
