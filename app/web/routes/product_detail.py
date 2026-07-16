from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from app.database import ApprovalRecord, PriceHistory, Product
from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct
from app.web.app import templates

router = APIRouter()
logger = logging.getLogger(__name__)

_MARKETPLACE_NAMES = {
    "ozon": "Ozon",
    "wildberries": "Wildberries",
    "yandex_market": "Яндекс Маркет",
}


def _detect_marketplace(url: str) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low or "yandex.ru/market" in low:
        return "yandex_market"
    return "unknown"


async def _get_product(request: Request, product_id: int) -> Product:
    db = request.app.state.db
    async with db.session() as s:
        product = await s.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return product


async def _get_price_history(request: Request, product_id: int) -> list[PriceHistory]:
    db = request.app.state.db
    async with db.session() as s:
        result = await s.execute(
            select(PriceHistory)
            .where(PriceHistory.product_id == product_id)
            .order_by(desc(PriceHistory.recorded_at))
            .limit(100)
        )
        return list(result.scalars().all())


async def _get_approval_records(request: Request, product_id: int) -> list[dict]:
    db = request.app.state.db
    async with db.session() as s:
        result = await s.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.product_id == str(product_id))
            .order_by(desc(ApprovalRecord.created_at))
            .limit(50)
        )
        records = result.scalars().all()
        return [
            {
                "approval_id": r.approval_id,
                "field": r.field,
                "suggestion_type": r.suggestion_type,
                "before_value": r.before_value,
                "after_value": r.after_value,
                "reason": r.reason,
                "confidence": r.confidence,
                "status": r.status,
                "reject_reason": r.reject_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            }
            for r in records
        ]


def _build_unified(product: Product, last_price) -> UnifiedProduct:
    marketplace = _detect_marketplace(product.url)
    return UnifiedProduct(
        name=product.name or "",
        source_id=str(product.id),
        source_type=marketplace,
        price=last_price.price if last_price else None,
        image_urls=[product.image_url] if product.image_url else [],
        thumbnail_url=product.image_url,
        marketplace=marketplace,
        availability=last_price.availability_status if last_price else "unknown",
        source_url=product.url,
    )


def _analysis_to_dict(analysis):
    return {
        "score": analysis.score,
        "tier": analysis.tier,
        "findings": [
            {
                "rule": f.rule,
                "field": f.field,
                "message": f.message,
                "severity": f.severity,
                "category": f.category,
            }
            for f in analysis.findings
        ],
        "recommendations": [
            {
                "action": r.action,
                "priority": r.priority,
                "description": r.description,
                "field": r.finding.field,
                "severity": r.finding.severity,
            }
            for r in analysis.recommendations
        ],
    }


# ── HTML routes ─────────────────────────────────────────────────────────

@router.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail_page(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    price_history = await _get_price_history(request, product_id)
    approval_records = await _get_approval_records(request, product_id)

    marketplace = _detect_marketplace(product.url)
    unified = _build_unified(product, last_price)
    analyzer = ProductAnalyzer()
    analysis = analyzer.analyze(unified)

    suggestions = [r for r in approval_records if r["status"] == "pending"]

    return templates.TemplateResponse(
        request,
        "product_detail.html",
        {
            "product": product,
            "last_price": last_price,
            "marketplace": marketplace,
            "marketplace_name": _MARKETPLACE_NAMES.get(marketplace, marketplace),
            "unified": unified,
            "analysis": analysis,
            "analysis_dict": _analysis_to_dict(analysis),
            "suggestions": suggestions,
            "approval_records": approval_records,
            "price_history": price_history,
            "active": "products",
        },
    )


# ── API routes ──────────────────────────────────────────────────────────

@router.get("/api/products/{product_id}")
async def api_product_detail(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    marketplace = _detect_marketplace(product.url)
    return {
        "id": product.id,
        "name": product.name,
        "url": product.url,
        "image_url": product.image_url,
        "marketplace": marketplace,
        "marketplace_name": _MARKETPLACE_NAMES.get(marketplace, marketplace),
        "current_price": last_price.price if last_price else None,
        "availability": last_price.availability_status if last_price else "unknown",
        "first_seen": product.first_seen.isoformat() if product.first_seen else None,
        "last_check": product.last_check.isoformat() if product.last_check else None,
    }


@router.get("/api/products/{product_id}/prices")
async def api_product_prices(product_id: int, request: Request):
    await _get_product(request, product_id)
    price_history = await _get_price_history(request, product_id)
    return [
        {
            "price": p.price,
            "availability_status": p.availability_status,
            "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
        }
        for p in price_history
    ]


@router.get("/api/products/{product_id}/analysis")
async def api_product_analysis(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    unified = _build_unified(product, last_price)
    analyzer = ProductAnalyzer()
    analysis = analyzer.analyze(unified)
    return _analysis_to_dict(analysis)


@router.get("/api/products/{product_id}/suggestions")
async def api_product_suggestions(product_id: int, request: Request):
    await _get_product(request, product_id)
    records = await _get_approval_records(request, product_id)
    return [r for r in records if r["status"] == "pending"]


@router.get("/api/products/{product_id}/history")
async def api_product_history(product_id: int, request: Request):
    await _get_product(request, product_id)
    return await _get_approval_records(request, product_id)


async def db_get_last_price(request: Request, product_id: int):
    db = request.app.state.db
    return await db.get_last_price(product_id)
