"""Pydantic schemas for store analytics API responses."""

from __future__ import annotations

from pydantic import BaseModel


class PriceStats(BaseModel):
    total_with_price: int
    min_price: int | None
    max_price: int | None
    avg_price: float | None
    median_price: float | None
    p25_price: float | None
    p75_price: float | None


class IssueCount(BaseModel):
    rule: str
    field: str
    category: str
    severity: str
    count: int
    affected_products: int


class ScoreDistribution(BaseModel):
    total: int
    average_score: float
    distribution: dict[str, int]
    percentage: dict[str, float]


class ProductAttention(BaseModel):
    product_id: int
    name: str | None
    url: str
    marketplace: str
    score: int
    tier: str
    critical_findings: list[str]
    warning_findings: list[str]
    last_price: int | None


class ImportDay(BaseModel):
    date: str
    imports: int
    successes: int
    failures: int


class MarketplaceAnalytics(BaseModel):
    marketplace: str
    total_products: int
    average_score: float
    score_distribution: dict[str, int]
    avg_price: float | None
    top_issues: list[IssueCount]


class StoreSummary(BaseModel):
    total_products: int
    marketplace: str | None
    average_score: float
    score_distribution: ScoreDistribution
    top_issues: list[IssueCount]
    products_below_threshold: int
    price_stats: PriceStats
