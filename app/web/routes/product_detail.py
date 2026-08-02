from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from app.ai_recommendation.db_approval import DatabaseApprovalQueue
from app.ai_recommendation.job_queue import process_product_ai_suggestion_job
from app.database import ApprovalRecord, PriceHistory, Product
from app.editor.service import ProductCardEditorService
from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct
from app.products.versioning import ProductVersion, ProductVersionBuilder, persisted_record_to_version
from app.seo_intelligence import audit_unified_product_seo
from app.timeline.repository import TimelineRepository
from app.timeline.service import TimelineService
from app.web.app import templates
from app.web.image_urls import product_image_src

if TYPE_CHECKING:
    from app.timeline.schemas import ProductHistoryEvent

router = APIRouter()
logger = logging.getLogger(__name__)

_MARKETPLACE_NAMES = {
    "ozon": "Ozon",
    "wildberries": "Wildberries",
    "yandex_market": "Яндекс Маркет",
}

_HISTORY_FILTERS = [
    {"value": "all", "label": "Все события"},
    {"value": "import", "label": "Импорт"},
    {"value": "price", "label": "Цена"},
    {"value": "stock", "label": "Остатки"},
    {"value": "ai", "label": "AI-рекомендации"},
    {"value": "decision", "label": "Одобрения и отклонения"},
    {"value": "manual", "label": "Ручные изменения"},
]

_TIMELINE_DEFAULT_LIMIT = 50
_TIMELINE_MAX_LIMIT = 200
_VERSION_DEFAULT_LIMIT = 50
_VERSION_MAX_LIMIT = 200


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


def _queue_from_request(request: Request) -> DatabaseApprovalQueue:
    queue = getattr(request.app.state, "ai_queue", None)
    if queue is None and hasattr(request.app.state, "db"):
        queue = DatabaseApprovalQueue(request.app.state.db)
        request.app.state.ai_queue = queue
    if not isinstance(queue, DatabaseApprovalQueue) and not all(hasattr(queue, name) for name in ("add", "get_all")):
        logger.warning("AI suggestions queue is not initialized")
        raise HTTPException(status_code=503, detail="AI suggestions queue is not initialized")
    return queue


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


async def _get_price_history_for_timeline(
    request: Request,
    product_id: int,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_limit: int = 500,
) -> list[PriceHistory]:
    db = request.app.state.db
    async with db.session() as s:
        stmt = select(PriceHistory).where(PriceHistory.product_id == product_id)
        if date_from is not None:
            stmt = stmt.where(PriceHistory.recorded_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(PriceHistory.recorded_at <= date_to)
        result = await s.execute(
            stmt.order_by(desc(PriceHistory.recorded_at)).limit(source_limit)
        )
        return list(result.scalars().all())


async def _get_approval_records(request: Request, product_id: int) -> list[dict]:
    records = await _get_approval_record_models(request, product_id)
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


async def _get_approval_record_models(request: Request, product_id: int) -> list[ApprovalRecord]:
    db = request.app.state.db
    async with db.session() as s:
        result = await s.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.product_id == str(product_id))
            .order_by(desc(ApprovalRecord.created_at))
            .limit(50)
        )
        return list(result.scalars().all())


async def _get_approval_record_models_for_timeline(
    request: Request,
    product_id: int,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_limit: int = 500,
) -> list[ApprovalRecord]:
    db = request.app.state.db
    async with db.session() as s:
        stmt = select(ApprovalRecord).where(ApprovalRecord.product_id == str(product_id))
        if date_from is not None:
            stmt = stmt.where(ApprovalRecord.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(ApprovalRecord.created_at <= date_to)
        result = await s.execute(
            stmt.order_by(desc(ApprovalRecord.created_at)).limit(source_limit)
        )
        return list(result.scalars().all())


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


def _seo_to_dict(seo):
    return {
        "score": seo.score,
        "tier": seo.tier,
        "ready": seo.ready,
        "findings": [
            {
                "rule": f.rule,
                "field": f.field,
                "severity": f.severity,
                "message": f.message,
            }
            for f in seo.findings
        ],
        "recommendations": [
            {
                "field": r.field,
                "action": r.action,
                "priority": r.priority,
                "reason": r.reason,
            }
            for r in seo.recommendations
        ],
    }


async def _get_product_history_events(
    request: Request,
    product: Product,
    *,
    event_filter: str = "all",
    limit: int = _TIMELINE_DEFAULT_LIMIT,
    offset: int = 0,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "newest_first",
) -> list[ProductHistoryEvent]:
    timeline = await _timeline_service(request).build_timeline(
        product=product,
        event_type=event_filter,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )
    return timeline.items


def _timeline_service(request: Request) -> TimelineService:
    return TimelineService(TimelineRepository(request.app.state.db))


def _parse_history_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "+"))
    except ValueError as exc:
        logger.info("Invalid timeline datetime filter: %s", value)
        raise HTTPException(status_code=422, detail="Некорректная дата фильтра истории") from exc


def _normalize_timeline_limit(limit: int) -> int:
    return max(1, min(limit, _TIMELINE_MAX_LIMIT))


def _normalize_timeline_offset(offset: int) -> int:
    return max(offset, 0)


def _normalize_timeline_sort(sort: str) -> str:
    if sort not in {"newest_first", "oldest_first"}:
        raise HTTPException(status_code=422, detail="Некорректная сортировка истории")
    return sort


async def _get_product_versions(
    request: Request,
    product: Product,
    *,
    limit: int = _VERSION_DEFAULT_LIMIT,
    offset: int = 0,
    version_type: str = "all",
    sort: str = "newest_first",
) -> list[ProductVersion]:
    persisted_records = await ProductCardEditorService(request.app.state.db).list_persisted_versions(
        product.id,
        limit=max(_VERSION_MAX_LIMIT, offset + limit + 50),
        offset=0,
    )
    persisted_versions = [persisted_record_to_version(record) for record in persisted_records]
    last_price = await db_get_last_price(request, product.id)
    unified = _build_unified(product, last_price)
    analysis = ProductAnalyzer().analyze(unified)
    events = await _get_product_history_events(
        request,
        product,
        limit=max(_VERSION_MAX_LIMIT, offset + limit + 50),
        sort="oldest_first",
    )
    builder = ProductVersionBuilder()
    derived_versions = builder.build(
        product=product,
        timeline_events=events,
        quality_score=analysis.score,
        limit=max(_VERSION_MAX_LIMIT, offset + limit + 50),
        offset=0,
        sort=sort,
        version_type=version_type,
    )
    versions = persisted_versions + derived_versions
    if version_type != "all":
        versions = [version for version in versions if version.version_type == version_type]
    versions.sort(key=lambda version: version.version_number, reverse=sort != "oldest_first")
    return versions[offset : offset + limit]


def _normalize_version_limit(limit: int) -> int:
    return max(1, min(limit, _VERSION_MAX_LIMIT))


def _normalize_version_offset(offset: int) -> int:
    return max(offset, 0)


def _normalize_version_sort(sort: str) -> str:
    if sort not in {"newest_first", "oldest_first"}:
        raise HTTPException(status_code=422, detail="Некорректная сортировка версий")
    return sort


def _normalize_version_number(value: int) -> int:
    if value < 1:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    return value


# ── HTML routes ─────────────────────────────────────────────────────────

@router.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail_page(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    price_history = await _get_price_history(request, product_id)
    approval_records = await _get_approval_records(request, product_id)
    history_events = await _get_product_history_events(request, product)

    marketplace = _detect_marketplace(product.url)
    unified = _build_unified(product, last_price)
    analyzer = ProductAnalyzer()
    analysis = analyzer.analyze(unified)
    seo = audit_unified_product_seo(unified)

    suggestions = [r for r in approval_records if r["status"] == "pending"]

    return templates.TemplateResponse(
        request,
        "product_detail.html",
        {
            "product": product,
            "product_image_src": product_image_src(product.name, product.image_url),
            "last_price": last_price,
            "marketplace": marketplace,
            "marketplace_name": _MARKETPLACE_NAMES.get(marketplace, marketplace),
            "unified": unified,
            "analysis": analysis,
            "analysis_dict": _analysis_to_dict(analysis),
            "seo": seo,
            "seo_dict": _seo_to_dict(seo),
            "suggestions": suggestions,
            "approval_records": approval_records,
            "history_events": history_events,
            "history_filters": _HISTORY_FILTERS,
            "history_filter": "all",
            "price_history": price_history,
            "active": "products",
        },
    )


@router.post("/api/products/{product_id}/ai-suggestions", response_class=HTMLResponse)
async def generate_product_ai_suggestions(product_id: int, request: Request, background_tasks: BackgroundTasks):
    product = await _get_product(request, product_id)
    _queue_from_request(request)
    job = await request.app.state.db.create_job(
        "ai_product_suggestions",
        {
            "product_id": product.id,
            "product_name": product.name or "",
            "product_url": product.url,
        },
    )
    background_tasks.add_task(process_product_ai_suggestion_job, request.app, job.job_id, product.id)

    ai_message = f"Задача {job.job_id} поставлена в очередь. Результат появится после выполнения."
    ai_message_type = "success"

    records = await _get_approval_records(request, product_id)
    suggestions = [r for r in records if r["status"] == "pending"]
    return templates.TemplateResponse(
        request,
        "product_ai_suggestions.html",
        {
            "product": product,
            "suggestions": suggestions,
            "ai_message": ai_message,
            "ai_message_type": ai_message_type,
            "job_id": job.job_id,
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


@router.get("/api/products/{product_id}/seo")
async def api_product_seo(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    unified = _build_unified(product, last_price)
    return _seo_to_dict(audit_unified_product_seo(unified))


@router.get("/api/products/{product_id}/semantic-core")
async def api_product_semantic_core(product_id: int, request: Request):
    """Возвращает семантическое ядро товара. Не мутирует БД."""
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    unified = _build_unified(product, last_price)
    from app.semantic_core import build_semantic_core
    core = build_semantic_core(
        name=unified.name,
        description=unified.description,
        attributes=dict(unified.attributes) if unified.attributes else None,
        category=unified.category,
        tags=unified.tags,
        brand=unified.brand,
    )
    return {
        "product_id": product_id,
        "primary_terms": core.primary_terms,
        "secondary_terms": core.secondary_terms,
        "long_tail_terms": core.long_tail_terms,
        "brand_terms": core.brand_terms,
        "attribute_terms": core.attribute_terms,
        "category_terms": core.category_terms,
        "forbidden_terms": core.forbidden_terms,
        "noisy_terms": core.noisy_terms,
        "total_terms": core.total_terms,
        "coverage_score": core.coverage_score,
        "junk_ratio": core.junk_ratio,
    }


@router.get("/products/{product_id}/semantic-core", response_class=HTMLResponse)
async def product_semantic_core_html(product_id: int, request: Request):
    """Возвращает HTML-фрагмент семантического ядра для HTMX."""
    product = await _get_product(request, product_id)
    last_price = await db_get_last_price(request, product_id)
    unified = _build_unified(product, last_price)
    from app.semantic_core import build_semantic_core
    core = build_semantic_core(
        name=unified.name,
        description=unified.description,
        attributes=dict(unified.attributes) if unified.attributes else None,
        category=unified.category,
        tags=unified.tags,
        brand=unified.brand,
    )
    return templates.TemplateResponse(
        request,
        "semantic_core_section.html",
        {
            "primary_terms": core.primary_terms,
            "secondary_terms": core.secondary_terms,
            "long_tail_terms": core.long_tail_terms,
            "total_terms": core.total_terms,
            "coverage_score": core.coverage_score,
            "junk_ratio": core.junk_ratio,
        },
    )


@router.get("/api/products/{product_id}/suggestions")
async def api_product_suggestions(product_id: int, request: Request):
    await _get_product(request, product_id)
    records = await _get_approval_records(request, product_id)
    return [r for r in records if r["status"] == "pending"]


@router.get("/api/products/{product_id}/history")
async def api_product_history(product_id: int, request: Request):
    await _get_product(request, product_id)
    return await _get_approval_records(request, product_id)


@router.get("/api/products/{product_id}/timeline")
async def api_product_timeline(
    product_id: int,
    request: Request,
    event_type: str = "all",
    source: str = "all",
    limit: int = Query(_TIMELINE_DEFAULT_LIMIT, ge=1, le=_TIMELINE_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "newest_first",
):
    product = await _get_product(request, product_id)
    safe_limit = _normalize_timeline_limit(limit)
    safe_offset = _normalize_timeline_offset(offset)
    safe_sort = _normalize_timeline_sort(sort)
    parsed_from = _parse_history_datetime(date_from)
    parsed_to = _parse_history_datetime(date_to)
    timeline = await _timeline_service(request).build_timeline(
        product=product,
        event_type=event_type,
        source=source,
        limit=safe_limit,
        offset=safe_offset,
        date_from=parsed_from,
        date_to=parsed_to,
        sort=safe_sort,
    )
    return timeline.to_dict()


@router.get("/products/{product_id}/history", response_class=HTMLResponse)
async def product_history_partial(
    product_id: int,
    request: Request,
    event_type: str = "all",
):
    product = await _get_product(request, product_id)
    events = await _get_product_history_events(
        request,
        product,
        event_filter=event_type,
        limit=_TIMELINE_DEFAULT_LIMIT,
    )
    return templates.TemplateResponse(
        request,
        "product_history.html",
        {
            "product": product,
            "history_events": events,
            "history_filters": _HISTORY_FILTERS,
            "history_filter": event_type,
        },
    )


@router.get("/products/{product_id}/versions", response_class=HTMLResponse)
async def product_versions_page(product_id: int, request: Request):
    product = await _get_product(request, product_id)
    versions = await _get_product_versions(request, product)
    return templates.TemplateResponse(
        request,
        "product_versions.html",
        {
            "product": product,
            "versions": versions,
            "active": "products",
        },
    )


@router.get("/products/{product_id}/compare", response_class=HTMLResponse)
async def product_compare_page(
    product_id: int,
    request: Request,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
):
    product = await _get_product(request, product_id)
    versions = await _get_product_versions(
        request,
        product,
        limit=_VERSION_MAX_LIMIT,
        sort="oldest_first",
    )
    builder = ProductVersionBuilder()
    source = builder.get_version(versions, _normalize_version_number(from_version))
    target = builder.get_version(versions, _normalize_version_number(to_version))
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    comparison = builder.compare(
        product_id=product.id,
        from_version=source,
        to_version=target,
    )
    return templates.TemplateResponse(
        request,
        "product_version_compare.html",
        {
            "product": product,
            "from_version": source,
            "to_version": target,
            "comparison": comparison,
            "active": "products",
        },
    )


@router.get("/api/products/{product_id}/versions")
async def api_product_versions(
    product_id: int,
    request: Request,
    limit: int = Query(_VERSION_DEFAULT_LIMIT, ge=1, le=_VERSION_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    version_type: str = "all",
    sort: str = "newest_first",
):
    product = await _get_product(request, product_id)
    safe_limit = _normalize_version_limit(limit)
    safe_offset = _normalize_version_offset(offset)
    safe_sort = _normalize_version_sort(sort)
    versions = await _get_product_versions(
        request,
        product,
        limit=safe_limit + 1,
        offset=safe_offset,
        version_type=version_type,
        sort=safe_sort,
    )
    visible_versions = versions[:safe_limit]
    has_more = len(versions) > safe_limit
    return {
        "product_id": product.id,
        "items": [version.to_dict() for version in visible_versions],
        "pagination": {
            "limit": safe_limit,
            "offset": safe_offset,
            "next_offset": safe_offset + safe_limit if has_more else None,
            "total_returned": len(visible_versions),
            "has_more": has_more,
            "sort": safe_sort,
        },
    }


@router.get("/api/products/{product_id}/versions/{version_number}")
async def api_product_version_detail(product_id: int, version_number: int, request: Request):
    product = await _get_product(request, product_id)
    versions = await _get_product_versions(
        request,
        product,
        limit=_VERSION_MAX_LIMIT,
        sort="oldest_first",
    )
    version = ProductVersionBuilder().get_version(
        versions,
        _normalize_version_number(version_number),
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    return version.to_dict()


@router.get("/api/products/{product_id}/compare")
async def api_product_version_compare(
    product_id: int,
    request: Request,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
):
    product = await _get_product(request, product_id)
    versions = await _get_product_versions(
        request,
        product,
        limit=_VERSION_MAX_LIMIT,
        sort="oldest_first",
    )
    builder = ProductVersionBuilder()
    source = builder.get_version(versions, _normalize_version_number(from_version))
    target = builder.get_version(versions, _normalize_version_number(to_version))
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    return builder.compare(
        product_id=product.id,
        from_version=source,
        to_version=target,
    ).to_dict()


async def db_get_last_price(request: Request, product_id: int):
    db = request.app.state.db
    return await db.get_last_price(product_id)
