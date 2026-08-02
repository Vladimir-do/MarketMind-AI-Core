from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.analytics.store_analyzer import StoreAnalyzer
from app.database import ApprovalRecord
from app.web.app import templates

router = APIRouter()


async def _suggestion_stats(request: Request) -> dict:
    db = request.app.state.db
    async with db.session() as s:
        result = await s.execute(select(ApprovalRecord.status))
        statuses = [row[0] for row in result.all()]
    counter = Counter(statuses)
    return {
        "total": len(statuses),
        "pending": counter.get("pending", 0),
        "approved": counter.get("approved", 0),
        "rejected": counter.get("rejected", 0),
        "rolled_back": counter.get("rolled_back", 0),
    }


async def build_client_report(request: Request) -> dict:
    analyzer = StoreAnalyzer(request.app.state.db)
    summary = await analyzer.get_store_summary()
    attention = await analyzer.get_products_needing_attention(threshold=60, limit=10)
    top_issues = await analyzer.get_top_issues(limit=10)
    marketplace_comparison = await analyzer.get_marketplace_comparison()
    suggestions = await _suggestion_stats(request)

    high_risk_count = sum(1 for item in attention if item.score < 40)
    report_status = "needs_attention" if summary.products_below_threshold else "good"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": report_status,
        "summary": summary.model_dump(),
        "top_issues": [item.model_dump() for item in top_issues],
        "attention_products": [item.model_dump() for item in attention],
        "marketplaces": [item.model_dump() for item in marketplace_comparison],
        "suggestions": suggestions,
        "high_risk_count": high_risk_count,
        "recommended_actions": _recommended_actions(summary.products_below_threshold, suggestions, len(top_issues)),
    }


def _recommended_actions(products_below_threshold: int, suggestions: dict, issue_count: int) -> list[str]:
    actions: list[str] = []
    if products_below_threshold:
        actions.append("Разобрать товары с низкой оценкой качества и заполнить недостающие данные.")
    if suggestions.get("pending", 0):
        actions.append("Проверить ожидающие AI-предложения и принять или отклонить каждое вручную.")
    if issue_count:
        actions.append("Начать с самых частых проблем: они дадут максимальный эффект на каталог.")
    if not actions:
        actions.append("Поддерживать регулярный импорт и контроль качества карточек.")
    return actions


@router.get("/api/reports/client-summary")
async def api_client_summary(request: Request):
    return await build_client_report(request)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    report = await build_client_report(request)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"report": report, "active": "reports"},
    )
