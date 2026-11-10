from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.app import templates
from app.web.schemas import DashboardStats, HealthSummary, MarketplaceStats

router = APIRouter()


def _detect_marketplace(url: str) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low or "yandex.ru/market" in low:
        return "yandex_market"
    return "unknown"


@router.get("/api/dashboard", response_model=DashboardStats)
async def dashboard_stats(request: Request):
    db = request.app.state.db
    products = await db.get_all_products()

    counter: Counter[str] = Counter()
    for p in products:
        counter[_detect_marketplace(p.url)] += 1

    marketplace_stats = [MarketplaceStats(marketplace=m, count=c) for m, c in counter.most_common()]

    attempts = await db.get_recent_scrape_attempts(limit=1000)
    blocks = await db.get_recent_blocked_patterns(limit=1000)
    mp_counter: Counter[str] = Counter(a.marketplace for a in attempts)
    health_markets = [MarketplaceStats(marketplace=m, count=c) for m, c in mp_counter.most_common()]

    return DashboardStats(
        total_products=len(products),
        products_by_marketplace=marketplace_stats,
        health_summary=HealthSummary(
            total_scrape_attempts=len(attempts),
            total_blocks=len(blocks),
            marketplaces=health_markets,
        ),
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    db = request.app.state.db
    products = await db.get_all_products()
    counter: Counter[str] = Counter()
    for p in products:
        counter[_detect_marketplace(p.url)] += 1
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"total": len(products), "by_marketplace": counter},
    )
