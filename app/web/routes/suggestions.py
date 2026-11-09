from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.ai_recommendation.db_approval import DatabaseApprovalQueue
from app.editor.service import EditorError, ProductCardEditorService
from app.effective_card.service import EffectiveProductCardService
from app.web.app import templates
from app.web.schemas import SuggestionItem, SuggestionStats

if TYPE_CHECKING:
    from app.ai_recommendation.approval import PendingApproval

router = APIRouter()
logger = logging.getLogger(__name__)


def _queue_from_request(request: Request) -> DatabaseApprovalQueue:
    queue = getattr(request.app.state, "ai_queue", None)
    if not isinstance(queue, DatabaseApprovalQueue):
        logger.warning("AI suggestions queue is not initialized")
        raise HTTPException(status_code=503, detail="AI suggestions queue is not initialized")
    return queue


def _status(item: PendingApproval) -> str:
    return "pending" if item.approved is None else ("approved" if item.approved else "rejected")


def _product_name(item: PendingApproval) -> str:
    value = item.suggestion.metadata.get("product_name") or item.suggestion.metadata.get("name")
    return str(value).strip() if value else item.product_id


def _item_to_schema(item: PendingApproval) -> SuggestionItem:
    s = item.suggestion
    return SuggestionItem(
        approval_id=item.approval_id,
        product_id=item.product_id,
        product_name=_product_name(item),
        field=s.field,
        suggestion_type=s.suggestion_type,
        before=s.before,
        after=s.after,
        reason=s.reason,
        confidence=s.confidence,
        status=_status(item),
    )


async def _build_stats(queue: DatabaseApprovalQueue) -> SuggestionStats:
    all_items = await queue.get_all()
    return SuggestionStats(
        total=len(all_items),
        pending=sum(1 for i in all_items if i.approved is None),
        approved=sum(1 for i in all_items if i.approved is True),
        rejected=sum(1 for i in all_items if i.approved is False),
    )


async def _recent_jobs(request: Request, limit: int = 10) -> list[dict[str, Any]]:
    db = getattr(request.app.state, "db", None)
    if db is None:
        queue = getattr(request.app.state, "ai_queue", None)
        db = getattr(queue, "_db", None)
    if db is None:
        return []
    jobs = await db.get_recent_jobs(limit=limit)
    result = []
    for job in jobs:
        if job.job_type not in {
            "seo_ai_suggestions",
            "ai_product_suggestions",
            "content_pipeline",
            "competitor_analysis_refresh",
        }:
            continue
        parsed_result = None
        if job.result_json:
            try:
                parsed_result = json.loads(job.result_json)
            except (TypeError, ValueError):
                parsed_result = None
        result.append(
            {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "progress": job.progress,
                "payload": job.payload_json,
                "result": parsed_result,
                "result_raw": job.result_json,
                "diagnostics": parsed_result if job.status == "failed" and isinstance(parsed_result, dict) else None,
                "error_class": job.error_class,
                "error_text": job.error_text,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "updated_at": job.updated_at,
            }
        )
    return result


async def _filter_items(items: list[PendingApproval], status: str | None) -> list[PendingApproval]:
    if status == "pending":
        return [i for i in items if i.approved is None]
    if status == "approved":
        return [i for i in items if i.approved is True]
    if status == "rejected":
        return [i for i in items if i.approved is False]
    return items


async def _get_item(queue: DatabaseApprovalQueue, approval_id: str) -> PendingApproval:
    items = await queue.get_all()
    for item in items:
        if item.approval_id == approval_id:
            return item
    logger.info("AI suggestion not found: %s", approval_id)
    raise HTTPException(status_code=404, detail="Suggestion not found")


async def _reject_reason(request: Request) -> str:
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            data = await request.json()
            return str(data.get("reason", "")).strip() if isinstance(data, dict) else ""
        form = await request.form()
        return str(form.get("reason", "")).strip()
    except Exception:
        logger.warning("Could not parse reject reason", exc_info=True)
        return ""


def _suggestion_payload(field: str, value: str) -> dict[str, Any]:
    if field == "tags":
        return {"tags": [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]}
    if field == "selling_points":
        return {"selling_points": [item.strip() for item in value.split("\n") if item.strip()]}
    return {field: value}


async def _apply_project_suggestion(request: Request, item: PendingApproval) -> None:
    """Apply an explicitly approved project-scoped suggestion to effective card."""
    metadata = item.suggestion.metadata or {}
    project_id = str(metadata.get("project_id") or "").strip()
    project_product_id = str(metadata.get("project_product_id") or "").strip()
    if not project_id or not project_product_id:
        return
    try:
        product_id = int(item.product_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Некорректный product_id в AI-предложении") from exc

    effective_service = EffectiveProductCardService(request.app.state.db)
    editor_service = ProductCardEditorService(request.app.state.db)
    before_card = await effective_service.get_effective_card(project_id, product_id)
    payload = _suggestion_payload(item.suggestion.field, item.suggestion.after)
    before_value = before_card.effective_snapshot.get(item.suggestion.field)
    requested_value = payload.get(item.suggestion.field)
    if before_value == requested_value:
        await _queue_from_request(request).mark_applied(
            item.approval_id,
            field=item.suggestion.field,
            before_value=before_value,
            after_value=requested_value,
        )
        return

    try:
        draft = await editor_service.create_draft(
            product_id,
            payload=payload,
            actor_id="ai_approval",
            comment=f"AI-предложение {item.approval_id}: {item.suggestion.reason}",
            project_id=project_id,
            project_product_id=project_product_id,
        )
        await editor_service.apply_draft(
            product_id,
            draft.draft_id,
            revision=draft.revision,
            actor_id="ai_approval",
            comment=f"Применено после согласования AI-предложения {item.approval_id}",
            project_id=project_id,
            project_product_id=project_product_id,
        )
    except EditorError as exc:
        logger.warning("Could not apply approved AI suggestion %s", item.approval_id, exc_info=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    after_card = await effective_service.get_effective_card(project_id, product_id)
    after_value = after_card.effective_snapshot.get(item.suggestion.field)
    await _queue_from_request(request).mark_applied(
        item.approval_id,
        field=item.suggestion.field,
        before_value=before_value,
        after_value=after_value,
    )


@router.get("/suggestions", response_class=HTMLResponse)
async def suggestions_page(request: Request):
    queue = _queue_from_request(request)
    stats = await _build_stats(queue)
    all_items = await queue.get_all()
    items = [_item_to_schema(i) for i in all_items]
    jobs = await _recent_jobs(request)
    return templates.TemplateResponse(
        request,
        "suggestions.html",
        {"stats": stats, "items": items, "jobs": jobs, "active": "suggestions"},
    )


@router.get("/suggestions/list", response_class=HTMLResponse)
async def suggestions_list(request: Request, status: str = "all"):
    queue = _queue_from_request(request)
    all_items = await queue.get_all()
    items = await _filter_items(all_items, status)
    schemas = [_item_to_schema(i) for i in items]
    return templates.TemplateResponse(request, "suggestions_table.html", {"items": schemas})


@router.get("/suggestions/{approval_id}", response_class=HTMLResponse)
async def suggestion_detail_page(approval_id: str, request: Request):
    queue = _queue_from_request(request)
    item = await _get_item(queue, approval_id)
    schema = _item_to_schema(item)
    return templates.TemplateResponse(request, "suggestions_detail.html", {"item": schema})


@router.get("/suggestions/{approval_id}/detail", response_class=HTMLResponse)
async def suggestion_detail_alias(approval_id: str, request: Request):
    return await suggestion_detail_page(approval_id, request)


@router.get("/api/suggestions")
async def api_suggestions(request: Request, status: str | None = None):
    queue = _queue_from_request(request)
    all_items = await queue.get_all()
    items = await _filter_items(all_items, status)
    return [_item_to_schema(i).model_dump() for i in items]


@router.get("/api/ai-suggestions")
async def api_ai_suggestions(request: Request, status: str | None = None):
    return await api_suggestions(request, status=status)


@router.get("/api/suggestions/stats")
async def api_suggestions_stats(request: Request):
    queue = _queue_from_request(request)
    return (await _build_stats(queue)).model_dump()


@router.get("/api/ai-suggestions/stats")
async def api_ai_suggestions_stats(request: Request):
    return await api_suggestions_stats(request)


@router.get("/api/ai-suggestions/jobs")
async def api_ai_suggestions_jobs(request: Request):
    return await _recent_jobs(request)


@router.get("/api/suggestions/{approval_id}")
async def api_suggestion_detail(approval_id: str, request: Request):
    queue = _queue_from_request(request)
    item = await _get_item(queue, approval_id)
    return _item_to_schema(item).model_dump()


@router.post("/suggestions/{approval_id}/approve", response_class=HTMLResponse)
async def approve_suggestion(approval_id: str, request: Request):
    queue = _queue_from_request(request)
    item = await queue.approve(approval_id)
    if item is None:
        logger.info("AI suggestion approve failed, not found: %s", approval_id)
        raise HTTPException(status_code=404, detail="Suggestion not found")
    try:
        await _apply_project_suggestion(request, item)
    except Exception:
        await queue.reset_pending(approval_id)
        raise
    item = await _get_item(queue, approval_id)
    schema = _item_to_schema(item)
    return templates.TemplateResponse(request, "suggestions_row.html", {"item": schema})


@router.post("/suggestions/{approval_id}/reject", response_class=HTMLResponse)
async def reject_suggestion(approval_id: str, request: Request):
    queue = _queue_from_request(request)
    reason = await _reject_reason(request)
    item = await queue.reject(approval_id, reason=reason)
    if item is None:
        logger.info("AI suggestion reject failed, not found: %s", approval_id)
        raise HTTPException(status_code=404, detail="Suggestion not found")
    schema = _item_to_schema(item)
    return templates.TemplateResponse(request, "suggestions_row.html", {"item": schema})


@router.get("/api/suggestions/history")
async def api_suggestions_history(request: Request, product_id: str | None = None, limit: int = 50):
    queue = _queue_from_request(request)
    return await queue.get_history(product_id=product_id, limit=limit)


@router.post("/api/suggestions/{approval_id}/rollback")
async def rollback_suggestion(approval_id: str, request: Request):
    queue = _queue_from_request(request)
    info = await queue.get_rollback_info(approval_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if info["snapshot_before"] is None:
        raise HTTPException(status_code=400, detail="No snapshot available for rollback")
    success = await queue.rollback(approval_id)
    if not success:
        raise HTTPException(status_code=500, detail="Rollback failed")
    return {
        "status": "rolled_back",
        "approval_id": approval_id,
        "field": info["field"],
        "product_id": info["product_id"],
        "original_value": info["snapshot_before"].get("value"),
    }
