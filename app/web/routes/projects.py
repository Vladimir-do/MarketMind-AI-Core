"""Client project API and UI routes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse

from app.editor.service import (
    EditorConflictError,
    EditorNotFoundError,
    EditorValidationError,
    ProductCardEditorService,
)
from app.effective_card.service import EffectiveProductCardService
from app.exports.service import ProjectExportService
from app.pipeline import ImportPipeline
from app.projects.service import (
    ProjectError,
    ProjectNotFoundError,
    ProjectService,
)
from app.reports.service import ClientDeliveryReportService
from app.web.app import templates
from app.workspace.files import WorkspaceError, store_source_file

router = APIRouter()
PROJECT_UPLOAD_FILE = File(...)


def _project_service(request: Request) -> ProjectService:
    return ProjectService(request.app.state.db)


def _effective_service(request: Request) -> EffectiveProductCardService:
    return EffectiveProductCardService(request.app.state.db)


def _project_to_dict(project) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "client_name": project.client_name,
        "marketplace": project.marketplace,
        "status": project.status,
        "description": project.description,
        "source_filename": project.source_filename,
        "source_file_hash": project.source_file_hash,
        "source_imported_at": project.source_imported_at.isoformat() if project.source_imported_at else None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
        "notes": project.notes,
        "export_directory": project.export_directory,
    }


def _file_to_dict(record) -> dict[str, Any]:
    return {
        "file_id": record.file_id,
        "project_id": record.project_id,
        "original_filename": record.original_filename,
        "stored_filename": record.stored_filename,
        "relative_path": record.relative_path,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "file_format": record.file_format,
        "row_count": record.row_count,
        "import_status": record.import_status,
        "import_errors": json.loads(record.import_errors_json or "[]"),
        "imported_at": record.imported_at.isoformat() if record.imported_at else None,
    }


def _artifact_to_dict(record) -> dict[str, Any]:
    return {
        "id": getattr(record, "export_id", None) or getattr(record, "report_id", None),
        "project_id": record.project_id,
        "file_format": record.file_format,
        "relative_path": record.relative_path,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _editor_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ProjectNotFoundError, EditorNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, EditorConflictError):
        return HTTPException(status_code=409, detail={"message": str(exc), "conflict": exc.conflict})
    if isinstance(exc, EditorValidationError):
        return HTTPException(status_code=422, detail=exc.validation.to_dict())
    if isinstance(exc, (ProjectError, WorkspaceError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Не удалось выполнить действие")


async def _request_data(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json()
    try:
        form = await request.form()
    except Exception:
        return {}
    return dict(form)


@router.post("/api/projects", status_code=status.HTTP_201_CREATED)
async def api_create_project(request: Request):
    body = await _request_data(request)
    try:
        project = await _project_service(request).create_project(
            name=body.get("name"),
            client_name=body.get("client_name"),
            marketplace=body.get("marketplace") or "unknown",
            description=body.get("description"),
            notes=body.get("notes"),
        )
        return _project_to_dict(project)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects")
async def api_list_projects(request: Request, include_archived: bool = False):
    projects = await _project_service(request).list_projects(include_archived=include_archived)
    return {"items": [_project_to_dict(project) for project in projects]}


@router.get("/api/projects/{project_id}")
async def api_get_project(project_id: str, request: Request):
    try:
        return _project_to_dict(await _project_service(request).get_project(project_id))
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.patch("/api/projects/{project_id}")
async def api_update_project(project_id: str, request: Request):
    try:
        return _project_to_dict(await _project_service(request).update_project(project_id, await _request_data(request)))
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/archive")
async def api_archive_project(project_id: str, request: Request):
    try:
        return _project_to_dict(await _project_service(request).archive_project(project_id))
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/imports")
async def api_import_project_file(project_id: str, request: Request, file: UploadFile = PROJECT_UPLOAD_FILE):
    try:
        await _project_service(request).get_project(project_id)
        content = await file.read()
        stored = store_source_file(project_id, file.filename or "upload.csv", content)
        pipeline = ImportPipeline()
        result = pipeline.run_file(stored.absolute_path)
        errors = [getattr(error, "message", str(error)) for error in result.errors]
        file_record, created = await _project_service(request).record_source_file(
            project_id,
            stored,
            row_count=result.import_metadata.get("rows_extracted"),
            errors=errors,
        )
        saved = 0
        changed = 0
        db = request.app.state.db
        for row_index, enriched in enumerate(result.enriched):
            product = enriched.product
            url = product.source_url or f"file://project/{project_id}/{product.source_id or uuid.uuid4().hex}"
            saved_product, _price_changed = await db.save_product(
                url,
                {
                    "name": product.name,
                    "price": product.price,
                    "image_url": product.image_urls[0] if product.image_urls else None,
                    "availability": product.availability or "in_stock",
                },
            )
            _project_product, was_changed = await _project_service(request).link_imported_product(
                project_id,
                saved_product,
                product,
                source_file_id=file_record.file_id,
                source_row_index=row_index,
            )
            saved += 1
            changed += 1 if was_changed else 0
        return {
            "task_id": uuid.uuid4().hex[:12],
            "status": "completed" if created else "duplicate_file",
            "project_id": project_id,
            "file": _file_to_dict(file_record),
            "total_products": saved,
            "changed_products": changed,
            "errors": len(errors),
            "message": f"Импортировано {saved} товаров, ошибок: {len(errors)}",
        }
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/imports")
async def api_list_project_imports(project_id: str, request: Request):
    try:
        files = await _project_service(request).list_files(project_id)
        return {"project_id": project_id, "items": [_file_to_dict(record) for record in files]}
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/products")
async def api_project_products(
    project_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        cards = await _effective_service(request).list_effective_cards(project_id, limit=limit, offset=offset)
        return {
            "project_id": project_id,
            "items": [card.to_dict() for card in cards],
            "pagination": {"limit": limit, "offset": offset, "total_returned": len(cards)},
        }
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/products/{product_id}")
async def api_project_product(project_id: str, product_id: int, request: Request):
    try:
        return (await _effective_service(request).get_effective_card(project_id, product_id)).to_dict()
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/products/{product_id}/effective-card")
async def api_project_effective_card(project_id: str, product_id: int, request: Request):
    return await api_project_product(project_id, product_id, request)


@router.get("/api/projects/{project_id}/products/{product_id}/quality")
async def api_project_quality(project_id: str, product_id: int, request: Request):
    try:
        return await _effective_service(request).quality(project_id, product_id)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/products/{product_id}/drafts")
async def api_project_create_draft(project_id: str, product_id: int, request: Request):
    body = await _request_data(request)
    try:
        project_product = await _project_service(request).get_project_product(project_id, product_id)
        draft = await ProductCardEditorService(request.app.state.db).create_draft(
            product_id,
            payload=body.get("payload") or {},
            base_version_id=body.get("base_version_id"),
            actor_id="operator",
            comment=body.get("comment"),
            project_id=project_id,
            project_product_id=project_product.project_product_id,
        )
        from app.web.routes.editor import _draft_to_dict

        return _draft_to_dict(draft)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/apply")
async def api_project_apply_draft(project_id: str, product_id: int, draft_id: str, request: Request):
    body = await _request_data(request)
    try:
        project_product = await _project_service(request).get_project_product(project_id, product_id)
        result = await ProductCardEditorService(request.app.state.db).apply_draft(
            product_id,
            draft_id,
            revision=int(body.get("revision") or 0),
            actor_id="operator",
            comment=body.get("comment"),
            project_id=project_id,
            project_product_id=project_product.project_product_id,
        )
        from app.web.routes.editor import _version_to_dict

        return {
            "version": _version_to_dict(result.version),
            "event": result.event.to_dict(),
            "diff": [item.to_dict() for item in result.diff],
        }
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/quality-preview")
async def api_project_draft_quality_preview(project_id: str, product_id: int, draft_id: str, request: Request):
    body = await _request_data(request)
    try:
        return await _effective_service(request).draft_quality_preview(project_id, product_id, body.get("payload") or {})
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/export-preview")
async def api_project_export_preview(project_id: str, request: Request, marketplace_profile: str = "universal"):
    try:
        return await ProjectExportService(request.app.state.db).preview(project_id, marketplace_profile=marketplace_profile)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/exports")
async def api_create_project_export(project_id: str, request: Request):
    body = await _request_data(request)
    try:
        record = await ProjectExportService(request.app.state.db).create_export(
            project_id,
            file_format=body.get("file_format") or "csv",
            marketplace_profile=body.get("marketplace_profile") or "universal",
        )
        return _artifact_to_dict(record)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/exports")
async def api_list_project_exports(project_id: str, request: Request):
    records = await ProjectExportService(request.app.state.db).list_exports(project_id)
    return {"project_id": project_id, "items": [_artifact_to_dict(record) for record in records]}


@router.get("/api/projects/{project_id}/report-preview")
async def api_project_report_preview(project_id: str, request: Request):
    try:
        return await ClientDeliveryReportService(request.app.state.db).preview(project_id)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/reports")
async def api_create_project_report(project_id: str, request: Request):
    body = await _request_data(request)
    try:
        record = await ClientDeliveryReportService(request.app.state.db).create_report(
            project_id,
            file_format=body.get("file_format") or "html",
        )
        return _artifact_to_dict(record)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/reports")
async def api_list_project_reports(project_id: str, request: Request):
    records = await ClientDeliveryReportService(request.app.state.db).list_reports(project_id)
    return {"project_id": project_id, "items": [_artifact_to_dict(record) for record in records]}


@router.get("/projects", response_class=HTMLResponse)
async def projects_page(request: Request):
    projects = await _project_service(request).list_projects()
    return templates.TemplateResponse(request, "projects.html", {"projects": projects, "active": "projects"})


@router.get("/projects/new", response_class=HTMLResponse)
async def project_new_page(request: Request):
    return templates.TemplateResponse(request, "project_new.html", {"active": "projects"})


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    products = await _effective_service(request).list_effective_cards(project_id, limit=10)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {"project": project, "products": products, "active": "projects"},
    )


@router.get("/projects/{project_id}/import", response_class=HTMLResponse)
async def project_import_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    return templates.TemplateResponse(request, "project_import.html", {"project": project, "active": "projects"})


@router.get("/projects/{project_id}/products", response_class=HTMLResponse)
async def project_products_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    products = await _effective_service(request).list_effective_cards(project_id)
    return templates.TemplateResponse(
        request,
        "project_products.html",
        {"project": project, "products": products, "active": "projects"},
    )


@router.get("/projects/{project_id}/reports", response_class=HTMLResponse)
async def project_reports_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    report = await ClientDeliveryReportService(request.app.state.db).preview(project_id)
    return templates.TemplateResponse(
        request,
        "project_reports.html",
        {"project": project, "report": report, "active": "projects"},
    )


@router.get("/projects/{project_id}/exports", response_class=HTMLResponse)
async def project_exports_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    exports = await ProjectExportService(request.app.state.db).list_exports(project_id)
    return templates.TemplateResponse(
        request,
        "project_exports.html",
        {"project": project, "exports": exports, "active": "projects"},
    )
