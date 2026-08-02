"""API routes for store analytics."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from .schemas import (
    ImportDay,
    IssueCount,
    MarketplaceAnalytics,
    PriceStats,
    ProductAttention,
    ScoreDistribution,
    StoreSummary,
)
from .store_analyzer import StoreAnalyzer

router = APIRouter()


def _analyzer(request: Request) -> StoreAnalyzer:
    return StoreAnalyzer(request.app.state.db)


@router.get("/api/analytics/store-summary", response_model=StoreSummary)
async def store_summary(
    request: Request,
    marketplace: str | None = Query(None),
):
    return await _analyzer(request).get_store_summary(marketplace)


@router.get("/api/analytics/score-distribution", response_model=ScoreDistribution)
async def score_distribution(
    request: Request,
    marketplace: str | None = Query(None),
):
    return await _analyzer(request).get_score_distribution(marketplace)


@router.get("/api/analytics/top-issues", response_model=list[IssueCount])
async def top_issues(
    request: Request,
    marketplace: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    return await _analyzer(request).get_top_issues(marketplace, limit)


@router.get("/api/analytics/needs-attention", response_model=list[ProductAttention])
async def needs_attention(
    request: Request,
    marketplace: str | None = Query(None),
    threshold: int = Query(50, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
):
    return await _analyzer(request).get_products_needing_attention(marketplace, threshold, limit)


@router.get("/api/analytics/price-stats", response_model=PriceStats)
async def price_stats(
    request: Request,
    marketplace: str | None = Query(None),
):
    return await _analyzer(request).get_price_statistics(marketplace)


@router.get("/api/analytics/import-history", response_model=list[ImportDay])
async def import_history(
    request: Request,
    marketplace: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    return await _analyzer(request).get_import_history(marketplace, days)


@router.get("/api/analytics/marketplace-comparison", response_model=list[MarketplaceAnalytics])
async def marketplace_comparison(request: Request):
    return await _analyzer(request).get_marketplace_comparison()
