"""Store catalog analyzer — computes analytics over all tracked products."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct

from .schemas import (
    ImportDay,
    IssueCount,
    MarketplaceAnalytics,
    PriceStats,
    ProductAttention,
    ScoreDistribution,
    StoreSummary,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.products.findings import AnalysisResult
    from app.database import Database, PriceHistory, Product


def _detect_marketplace(url: str) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low or "yandex.ru/market" in low:
        return "yandex_market"
    if "funpay" in low:
        return "funpay"
    return "unknown"


def _build_unified(product: Product, last_price: PriceHistory | None) -> UnifiedProduct:
    mp = _detect_marketplace(product.url)
    return UnifiedProduct(
        name=product.name or "",
        source_id=str(product.id),
        source_type=mp,
        price=last_price.price if last_price else None,
        source_url=product.url,
        marketplace=mp,
        availability=last_price.availability_status if last_price else "unknown",
    )


class StoreAnalyzer:
    """Aggregate analytics over the product catalog."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._analyzer = ProductAnalyzer()

    # ── public API ─────────────────────────────────────────────────────

    async def get_store_summary(self, marketplace: str | None = None) -> StoreSummary:
        products = await self._load_products(marketplace)
        analyses = self._analyze_products(products)
        price_stats = self._compute_price_stats(products)
        score_dist = self._build_score_distribution(analyses)
        top_issues = self._aggregate_issues(analyses, limit=10)
        below_threshold = sum(1 for a in analyses if a.score < 50)
        avg = score_dist.average_score

        return StoreSummary(
            total_products=len(products),
            marketplace=marketplace,
            average_score=avg,
            score_distribution=score_dist,
            top_issues=top_issues,
            products_below_threshold=below_threshold,
            price_stats=price_stats,
        )

    async def get_score_distribution(self, marketplace: str | None = None) -> ScoreDistribution:
        products = await self._load_products(marketplace)
        analyses = self._analyze_products(products)
        return self._build_score_distribution(analyses)

    async def get_top_issues(
        self, marketplace: str | None = None, limit: int = 10
    ) -> list[IssueCount]:
        products = await self._load_products(marketplace)
        analyses = self._analyze_products(products)
        return self._aggregate_issues(analyses, limit=limit)

    async def get_products_needing_attention(
        self, marketplace: str | None = None, threshold: int = 50, limit: int = 20
    ) -> list[ProductAttention]:
        products = await self._load_products(marketplace)
        items: list[ProductAttention] = []
        for product, last_price in products:
            unified = _build_unified(product, last_price)
            result = self._analyzer.analyze(unified)
            if result.score >= threshold:
                continue
            critical = [f.message for f in result.findings if f.severity == "critical"]
            warnings = [f.message for f in result.findings if f.severity == "warning"]
            items.append(
                ProductAttention(
                    product_id=product.id,
                    name=product.name,
                    url=product.url,
                    marketplace=_detect_marketplace(product.url),
                    score=result.score,
                    tier=result.tier,
                    critical_findings=critical,
                    warning_findings=warnings,
                    last_price=last_price.price if last_price else None,
                )
            )
        items.sort(key=lambda x: x.score)
        return items[:limit]

    async def get_price_statistics(self, marketplace: str | None = None) -> PriceStats:
        products = await self._load_products(marketplace)
        return self._compute_price_stats(products)

    async def get_import_history(
        self, marketplace: str | None = None, days: int = 30
    ) -> list[ImportDay]:
        since = datetime.now(UTC) - timedelta(days=days)
        # SQLite stores naive datetimes; strip tz for comparison
        since_naive = since.replace(tzinfo=None)
        attempts = await self._db.get_recent_scrape_attempts(
            limit=10_000, marketplace=marketplace
        )
        recent = [a for a in attempts if a.recorded_at and a.recorded_at >= since_naive]

        by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "ok": 0})
        for a in recent:
            day = a.recorded_at.strftime("%Y-%m-%d")
            by_day[day]["total"] += 1
            if a.status == "ok":
                by_day[day]["ok"] += 1

        result: list[ImportDay] = []
        for day_str in sorted(by_day.keys()):
            counts = by_day[day_str]
            result.append(
                ImportDay(
                    date=day_str,
                    imports=counts["total"],
                    successes=counts["ok"],
                    failures=counts["total"] - counts["ok"],
                )
            )
        return result

    async def get_marketplace_comparison(self) -> list[MarketplaceAnalytics]:
        products = await self._load_products(None)
        by_mp: dict[str, list[tuple[Product, PriceHistory | None]]] = defaultdict(list)
        for prod, price in products:
            mp = _detect_marketplace(prod.url)
            by_mp[mp].append((prod, price))

        result: list[MarketplaceAnalytics] = []
        for mp, items in sorted(by_mp.items()):
            analyses = self._analyze_products(items)
            prices = [p.price for _, p in items if p and p.price is not None]
            avg_price = float(statistics.mean(prices)) if prices else None
            score_dist = self._build_score_distribution(analyses)
            issues = self._aggregate_issues(analyses, limit=5)
            result.append(
                MarketplaceAnalytics(
                    marketplace=mp,
                    total_products=len(items),
                    average_score=score_dist.average_score,
                    score_distribution=score_dist.distribution,
                    avg_price=avg_price,
                    top_issues=issues,
                )
            )
        return result

    # ── private helpers ────────────────────────────────────────────────

    async def _load_products(
        self, marketplace: str | None
    ) -> list[tuple[Product, PriceHistory | None]]:
        all_products = await self._db.get_all_products()
        pairs: list[tuple[Product, PriceHistory | None]] = []
        for p in all_products:
            mp = _detect_marketplace(p.url)
            if marketplace and mp != marketplace:
                continue
            last_price = await self._db.get_last_price(p.id)
            pairs.append((p, last_price))
        return pairs

    def _analyze_products(
        self, products: list[tuple[Product, PriceHistory | None]]
    ) -> list[AnalysisResult]:
        results: list[AnalysisResult] = []
        for product, last_price in products:
            unified = _build_unified(product, last_price)
            results.append(self._analyzer.analyze(unified))
        return results

    def _build_score_distribution(self, analyses: list[AnalysisResult]) -> ScoreDistribution:
        total = len(analyses)
        if total == 0:
            return ScoreDistribution(total=0, average_score=0.0, distribution={}, percentage={})

        dist: Counter[str] = Counter()
        for a in analyses:
            dist[a.tier] += 1

        avg = round(sum(a.score for a in analyses) / total, 1)
        distribution = dict(dist)
        percentage = {k: round(v / total * 100, 1) for k, v in distribution.items()}
        return ScoreDistribution(
            total=total, average_score=avg, distribution=distribution, percentage=percentage
        )

    def _aggregate_issues(
        self, analyses: list[AnalysisResult], limit: int = 10
    ) -> list[IssueCount]:
        issue_map: dict[tuple, dict] = {}
        for a in analyses:
            for f in a.findings:
                key = (f.rule, f.field, f.category, f.severity)
                if key not in issue_map:
                    issue_map[key] = {
                        "rule": f.rule,
                        "field": f.field,
                        "category": f.category,
                        "severity": f.severity,
                        "count": 0,
                        "products": set(),
                    }
                issue_map[key]["count"] += 1
                issue_map[key]["products"].add(a.product.source_id)

        items = sorted(issue_map.values(), key=lambda x: x["count"], reverse=True)[:limit]
        return [
            IssueCount(
                rule=i["rule"],
                field=i["field"],
                category=i["category"],
                severity=i["severity"],
                count=i["count"],
                affected_products=len(i["products"]),
            )
            for i in items
        ]

    def _compute_price_stats(
        self, products: list[tuple[Product, PriceHistory | None]]
    ) -> PriceStats:
        prices = [p.price for _, p in products if p and p.price is not None]
        if not prices:
            return PriceStats(
                total_with_price=0,
                min_price=None,
                max_price=None,
                avg_price=None,
                median_price=None,
                p25_price=None,
                p75_price=None,
            )
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        return PriceStats(
            total_with_price=n,
            min_price=sorted_prices[0],
            max_price=sorted_prices[-1],
            avg_price=round(statistics.mean(prices), 2),
            median_price=round(statistics.median(prices), 2),
            p25_price=round(sorted_prices[n // 4], 2),
            p75_price=round(sorted_prices[3 * n // 4], 2),
        )
