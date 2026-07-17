"""Product card editor API and UI routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response

from app.editor.service import (
    EditorConflictError,
    EditorNotFoundError,
    EditorValidationError,
    ProductCardEditorService,
)
from app.web.app import templates

router = APIRouter()


def _service(request: Request) -> ProductCardEditorService:
    return ProductCardEditorService(request.app.state.db)


def _draft_to_dict(draft) -> dict[str, Any]:
    import json

    return {
        "draft_id": draft.draft_id,
        "product_id": draft.product_id,
        "base_version_id": draft.base_version_id,
        "status": draft.status,
        "payload": json.loads(draft.payload_json or "{}"),
        "validation": json.loads(draft.validation_json or "null"),
        "created_by": draft.created_by,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "revision": draft.revision,
        "comment": draft.comment,
    }


def _version_to_dict(version) -> dict[str, Any]:
    import json

    return {
        "version_id": version.version_id,
        "product_id": version.product_id,
        "version_number": version.version_number,
        "snapshot": json.loads(version.snapshot_json),
        "snapshot_schema_version": version.snapshot_schema_version,
        "source": version.source,
        "actor_type": version.actor_type,
        "actor_id": version.actor_id,
        "comment": version.comment,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "base_version_id": version.base_version_id,
        "trigger_event_id": version.trigger_event_id,
        "checksum": version.checksum,
        "is_derived": False,
        "snapshot_completeness": "complete",
    }


def _editor_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EditorNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, EditorConflictError):
        return HTTPException(status_code=409, detail={"message": str(exc), "conflict": exc.conflict})
    if isinstance(exc, EditorValidationError):
        return HTTPException(status_code=422, detail=exc.validation.to_dict())
    return HTTPException(status_code=500, detail="Не удалось выполнить действие редактора")


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def product_edit_page(product_id: int, request: Request):
    try:
        drafts = await _service(request).list_drafts(product_id, status="draft")
    except EditorNotFoundError as exc:
        raise _editor_error(exc) from exc
    return templates.TemplateResponse(
        request,
        "product_edit.html",
        {
            "product_id": product_id,
            "drafts": drafts,
            "active": "products",
        },
    )


@router.get("/products/{product_id}/drafts", response_class=HTMLResponse)
async def product_drafts_page(product_id: int, request: Request):
    try:
        drafts = await _service(request).list_drafts(product_id)
    except EditorNotFoundError as exc:
        raise _editor_error(exc) from exc
    return templates.TemplateResponse(
        request,
        "product_drafts.html",
        {
            "product_id": product_id,
            "drafts": drafts,
            "active": "products",
        },
    )


@router.get("/products/{product_id}/audit", response_class=HTMLResponse)
async def product_audit_page(product_id: int, request: Request):
    events = await _service(request).list_audit_events(product_id)
    return templates.TemplateResponse(
        request,
        "product_audit.html",
        {
            "product_id": product_id,
            "events": events,
            "active": "products",
        },
    )


@router.post("/api/products/{product_id}/drafts", status_code=status.HTTP_201_CREATED)
async def api_create_draft(product_id: int, request: Request):
    body = await request.json()
    try:
        draft = await _service(request).create_draft(
            product_id,
            payload=body.get("payload") or {},
            base_version_id=body.get("base_version_id"),
            actor_id=body.get("actor_id") or "local_user",
            comment=body.get("comment"),
        )
        return _draft_to_dict(draft)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/products/{product_id}/drafts")
async def api_list_drafts(
    product_id: int,
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
):
    try:
        drafts = await _service(request).list_drafts(product_id, status=status_filter)
        return {"product_id": product_id, "items": [_draft_to_dict(draft) for draft in drafts]}
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/products/{product_id}/drafts/{draft_id}")
async def api_get_draft(product_id: int, draft_id: str, request: Request):
    try:
        drafts = await _service(request).list_drafts(product_id)
        for draft in drafts:
            if draft.draft_id == draft_id:
                return _draft_to_dict(draft)
        raise EditorNotFoundError("Черновик не найден")
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.patch("/api/products/{product_id}/drafts/{draft_id}")
async def api_update_draft(product_id: int, draft_id: str, request: Request):
    body = await request.json()
    try:
        draft = await _service(request).update_draft(
            product_id,
            draft_id,
            payload=body.get("payload") or {},
            revision=int(body.get("revision") or 0),
            comment=body.get("comment"),
        )
        return _draft_to_dict(draft)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.delete("/api/products/{product_id}/drafts/{draft_id}")
async def api_discard_draft(product_id: int, draft_id: str, request: Request):
    try:
        await _service(request).discard_draft(product_id, draft_id)
        return Response(status_code=204)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/products/{product_id}/drafts/{draft_id}/validate")
async def api_validate_draft(product_id: int, draft_id: str, request: Request):
    try:
        return (await _service(request).validate_draft(product_id, draft_id)).to_dict()
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/products/{product_id}/drafts/{draft_id}/apply")
async def api_apply_draft(product_id: int, draft_id: str, request: Request):
    body = await request.json()
    try:
        result = await _service(request).apply_draft(
            product_id,
            draft_id,
            revision=int(body.get("revision") or 0),
            actor_id=body.get("actor_id") or "local_user",
            comment=body.get("comment"),
        )
        return {
            "version": _version_to_dict(result.version),
            "event": result.event.to_dict(),
            "diff": [item.to_dict() for item in result.diff],
        }
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/products/{product_id}/versions/{version_number}/rollback")
async def api_rollback_version(product_id: int, version_number: int, request: Request):
    body = await request.json()
    try:
        result = await _service(request).rollback_version(
            product_id,
            version_number,
            current_version_id=body.get("current_version_id"),
            actor_id=body.get("actor_id") or "local_user",
            reason=body.get("reason"),
        )
        return {
            "version": _version_to_dict(result.version),
            "event": result.event.to_dict(),
            "diff": [item.to_dict() for item in result.diff],
        }
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/products/{product_id}/audit")
async def api_product_audit(
    product_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    events = await _service(request).list_audit_events(product_id, limit=limit, offset=offset)
    return {
        "product_id": product_id,
        "items": [event.to_dict() for event in events],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_returned": len(events),
        },
    }
