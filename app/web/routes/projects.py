"""Client project API and UI routes."""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.ai_recommendation.db_approval import DatabaseApprovalQueue
from app.ai_recommendation.job_queue import process_project_seo_suggestion_job
from app.ai_recommendation.suggestions import AISuggestion
from app.config import IMPORT_SCHEMA_VERSION
from app.database import ProjectExport, ProjectReport
from app.editor.service import (
    EditorConflictError,
    EditorNotFoundError,
    EditorValidationError,
    ProductCardEditorService,
)
from app.effective_card.service import EffectiveProductCardService
from app.exports.safety import sanitize_spreadsheet_cell
from app.exports.service import ProjectExportService
from app.market_analysis import market_analysis_filename, market_analysis_products_to_rows, run_market_analysis
from app.pipeline import ImportPipeline
from app.projects.imports import analyze_import_file, build_products_from_preview
from app.projects.archive import ProjectArchiveService
from app.projects.service import (
    ProjectError,
    ProjectNotFoundError,
    ProjectService,
)
from app.reports.service import ClientDeliveryReportService
from app.web.app import templates
from app.workspace.files import WorkspaceError, project_root, store_source_file, stored_source_file

router = APIRouter()
logger = logging.getLogger(__name__)
PROJECT_UPLOAD_FILE = File(...)
PROJECT_OPTIONAL_UPLOAD_FILE = File(None)
FIELD_OPTIONS = [
    ("title", "Название"),
    ("description", "Описание"),
    ("brand", "Бренд"),
    ("category", "Категория"),
    ("price", "Цена"),
    ("old_price", "Старая цена"),
    ("cost", "Себестоимость"),
    ("availability", "Остаток / наличие"),
    ("marketplace", "Маркетплейс"),
    ("sku", "SKU"),
    ("vendor_code", "Артикул"),
    ("barcode", "Штрихкод"),
    ("source_url", "URL"),
    ("image_urls", "Изображения"),
    ("attributes", "Дополнительная характеристика"),
    ("skip", "Пропустить"),
]

WB_CABLE_MANAGEMENT_CANDIDATES = [
    {
        "Название": "Держатели кабеля самоклеящиеся 6 шт",
        "Описание": "Организация проводов на столе, у розетки и возле зарядок. Проверить конкурентов, силу клеевого слоя, отзывы и комплектацию.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "299",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=клей; плюс=компактный набор",
    },
    {
        "Название": "Органайзер для проводов настольный",
        "Описание": "Компактный аксессуар для порядка на рабочем месте: кабели, зарядки, провода, USB. Проверить конкурентов, отзывы, цену и читаемость карточек.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "399",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=конкуренция; плюс=понятная боль",
    },
    {
        "Название": "Кабельные клипсы для зарядок",
        "Описание": "Клипсы для фиксации зарядных кабелей на столе, тумбе или стене. Проверить спрос, дизайн, материал и количество штук в комплекте.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "249",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=низкий чек; плюс=легко показать применение",
    },
    {
        "Название": "Стяжки-липучки для проводов",
        "Описание": "Многоразовые липучки для аккуратной фиксации проводов, кабелей и зарядок дома, в офисе и в поездке. Проверить конкурентов и варианты комплектов.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "199",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=низкая цена; плюс=простая логистика",
    },
    {
        "Название": "Короб для проводов под стол",
        "Описание": "Короб для скрытия удлинителя и проводов под столом или возле рабочего места. Проверить габариты, логистику, отзывы и конкуренцию.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "799",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=габарит; плюс=выше средний чек",
    },
    {
        "Название": "Набор для кабель-менеджмента рабочего места",
        "Описание": "Комплект для организации проводов: держатели, клипсы и стяжки для рабочего стола, компьютера и зарядок. Проверить состав набора, цену и конкурентные карточки.",
        "Бренд": "NoBrand",
        "Категория": "Организация хранения",
        "Цена": "699",
        "Маркетплейс": "Wildberries",
        "Дополнительная характеристика": "кандидат_линейки=да; ниша=кабель-менеджмент; риск=комплектация; плюс=можно отличаться набором",
    },
]


def _project_service(request: Request) -> ProjectService:
    return ProjectService(request.app.state.db)


def _effective_service(request: Request) -> EffectiveProductCardService:
    return EffectiveProductCardService(request.app.state.db)


def _approval_queue(request: Request) -> DatabaseApprovalQueue:
    queue = getattr(request.app.state, "ai_queue", None)
    if isinstance(queue, DatabaseApprovalQueue):
        return queue
    queue = DatabaseApprovalQueue(request.app.state.db)
    request.app.state.ai_queue = queue
    return queue


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
        "schema_version": record.schema_version,
        "encoding": record.encoding,
        "delimiter": record.delimiter,
        "selected_sheet": record.selected_sheet,
        "row_count": record.row_count,
        "successful_rows": record.successful_rows,
        "warning_count": record.warning_count,
        "error_count": record.error_count,
        "import_status": record.import_status,
        "import_errors": json.loads(record.import_errors_json or "[]"),
        "import_summary": json.loads(record.import_summary_json or "{}"),
        "imported_at": record.imported_at.isoformat() if record.imported_at else None,
    }


def _preset_to_dict(record) -> dict[str, Any]:
    return {
        "preset_id": record.preset_id,
        "project_id": record.project_id,
        "name": record.name,
        "marketplace": record.marketplace,
        "schema_version": record.schema_version,
        "source_columns": json.loads(record.source_columns_json or "[]"),
        "mapping": json.loads(record.mapping_json or "{}"),
        "header_fingerprint": record.header_fingerprint,
        "active": record.active,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
    }


def _artifact_to_dict(record) -> dict[str, Any]:
    return {
        "id": getattr(record, "export_id", None) or getattr(record, "report_id", None),
        "project_id": record.project_id,
        "file_format": record.file_format,
        "relative_path": record.relative_path,
        "checksum": getattr(record, "checksum", None),
        "manifest": json.loads(getattr(record, "manifest_json", None) or "{}"),
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _seo_suggestion_preview(product_id: int, suggestion: AISuggestion) -> dict[str, Any]:
    return {
        "product_id": str(product_id),
        "product_name": str(suggestion.metadata.get("product_name") or product_id),
        "field": suggestion.field,
        "suggestion_type": suggestion.suggestion_type,
        "before": suggestion.before,
        "after": suggestion.after,
        "reason": suggestion.reason,
        "confidence": suggestion.confidence,
        "source_finding": suggestion.source_finding,
        "metadata": suggestion.metadata,
        "status": "draft",
    }


def _job_to_dict(record) -> dict[str, Any]:
    return {
        "job_id": record.job_id,
        "job_type": record.job_type,
        "status": record.status,
        "progress": record.progress,
        "payload": json.loads(record.payload_json or "{}"),
        "result": json.loads(record.result_json or "{}") if record.result_json else None,
        "error_class": record.error_class,
        "error_text": record.error_text,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _approval_to_dict(item) -> dict[str, Any]:
    suggestion = item.suggestion
    return {
        "approval_id": item.approval_id,
        "product_id": item.product_id,
        "product_name": str(suggestion.metadata.get("product_name") or item.product_id),
        "field": suggestion.field,
        "suggestion_type": suggestion.suggestion_type,
        "before": suggestion.before,
        "after": suggestion.after,
        "reason": suggestion.reason,
        "confidence": suggestion.confidence,
        "source_finding": suggestion.source_finding,
        "metadata": suggestion.metadata,
        "status": "pending" if item.approved is None else ("approved" if item.approved else "rejected"),
    }


def _is_hx(request: Request) -> bool:
    return request.headers.get("hx-request", "").lower() == "true"


def _trace_request(request: Request) -> None:
    logger.debug("%s %s hx=%s", request.method, request.url.path, _is_hx(request))


def _mapping_from_body(body: dict[str, Any]) -> dict[str, str]:
    mapping = body.get("mapping")
    if isinstance(mapping, dict):
        return {str(key): str(value) for key, value in mapping.items()}
    result = {}
    for key, value in body.items():
        if key.startswith("mapping__"):
            result[key.removeprefix("mapping__")] = str(value)
    return result


def _stored_file_from_body(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body.get("stored_file"), dict):
        return body["stored_file"]
    return {
        "relative_path": body.get("stored_relative_path"),
        "original_filename": body.get("stored_original_filename"),
        "sha256": body.get("stored_sha256"),
        "size_bytes": body.get("stored_size_bytes"),
        "file_format": body.get("stored_file_format"),
    }


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    if not rows:
        return b""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


async def _import_stored_file(
    request: Request,
    project_id: str,
    stored,
    *,
    body: dict[str, Any] | None = None,
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    body = body or {}
    duplicate = await _project_service(request).source_file_exists(project_id, stored.sha256)
    confirm_duplicate = allow_duplicate or bool(body.get("confirm_duplicate"))
    confirm_warnings = bool(body.get("confirm_warnings"))
    preview = analyze_import_file(
        path=stored.absolute_path,
        original_filename=stored.original_filename,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        file_format=stored.file_format,
        duplicate=duplicate,
        selected_sheet=body.get("selected_sheet"),
    )
    if duplicate and not confirm_duplicate:
        return {
            "status": "duplicate_file",
            "project_id": project_id,
            "preview": preview.to_dict(),
            "message": "Этот файл уже импортировался. Подтвердите повторный импорт, чтобы обновить данные.",
        }
    if preview.requires_confirmation and not confirm_warnings:
        return {
            "status": "warning_confirmation_required",
            "project_id": project_id,
            "preview": preview.to_dict(),
            "message": "В preview есть предупреждения. Подтвердите импорт после проверки.",
        }
    mapping = _mapping_from_body(body)
    preset_id = str(body.get("preset_id") or "").strip()
    if preset_id:
        preset = await _project_service(request).get_mapping_preset(project_id, preset_id)
        preset_mapping = json.loads(preset.mapping_json or "{}")
        if preset.header_fingerprint != preview.header_fingerprint and not confirm_warnings:
            return {
                "status": "preset_mismatch",
                "project_id": project_id,
                "preview": preview.to_dict(),
                "message": "Структура файла отличается от сохранённого сопоставления. Проверьте колонки и подтвердите импорт.",
            }
        mapping = mapping or preset_mapping
        await _project_service(request).touch_mapping_preset(project_id, preset_id)
    products, import_errors = build_products_from_preview(preview, mapping=mapping or None)
    pipeline = ImportPipeline()
    result = pipeline.run_products(products)
    errors = [getattr(error, "message", str(error)) for error in result.errors]
    errors.extend(error.message for error in import_errors)
    file_record, created = await _project_service(request).record_source_file(
        project_id,
        stored,
        row_count=preview.row_count,
        successful_rows=len(result.enriched),
        warning_count=len(preview.warnings),
        error_count=len(errors),
        errors=errors,
        schema_version=IMPORT_SCHEMA_VERSION,
        encoding=preview.encoding,
        delimiter=preview.delimiter,
        selected_sheet=preview.selected_sheet,
        summary=preview.to_dict(),
    )
    saved = 0
    changed = 0
    db = request.app.state.db
    for row_index, enriched in enumerate(result.enriched):
        product = enriched.product
        url = product.source_url or f"file://project/{project_id}/{product.source_id or uuid.uuid4().hex}"
        image_url = product.thumbnail_url or (product.image_urls[0] if product.image_urls else None)
        saved_product, _price_changed = await db.save_product(
            url,
            {
                "name": product.name,
                "price": product.price,
                "image_url": image_url,
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
    if body.get("save_preset") and mapping:
        await _project_service(request).save_mapping_preset(
            project_id,
            name=str(body.get("preset_name") or f"Сопоставление {stored.original_filename}"),
            marketplace=str(body.get("marketplace") or "unknown"),
            schema_version=IMPORT_SCHEMA_VERSION,
            source_columns=preview.columns,
            mapping=mapping,
            header_fingerprint=preview.header_fingerprint or "",
        )
    return {
        "task_id": uuid.uuid4().hex[:12],
        "status": "completed" if created else "reimported_existing_file",
        "project_id": project_id,
        "file": _file_to_dict(file_record),
        "total_products": saved,
        "changed_products": changed,
        "errors": len(errors),
        "message": f"Импортировано {saved} товаров, ошибок: {len(errors)}",
    }


def _preview_error_counts(preview) -> dict[str, int]:
    warning_count = len(preview.warnings)
    error_count = len(preview.errors)
    return {
        "errors": error_count,
        "warnings": warning_count,
        "valid_rows": max(preview.row_count - error_count, 0),
        "skipped_rows": error_count,
        "importable_rows": max(preview.row_count - error_count, 0),
    }


def _error_csv_response(project_id: str, preview) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["row_number", "column", "code", "value_preview", "message", "recommendation", "severity"],
    )
    writer.writeheader()
    for warning in preview.warnings:
        writer.writerow(
            {
                "row_number": 0,
                "column": "",
                "code": "warning",
                "value_preview": "",
                "message": sanitize_spreadsheet_cell(warning),
                "recommendation": "Проверьте preview и подтвердите импорт только если данные распознаны правильно.",
                "severity": "warning",
            }
        )
    for error in preview.errors:
        data = error.to_dict()
        writer.writerow({key: sanitize_spreadsheet_cell(str(data.get(key) or "")) for key in writer.fieldnames})
    filename = f"errors_{project_id}_{uuid.uuid4().hex[:8]}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        if _is_hx(request):
            return templates.TemplateResponse(
                request,
                "project_create_result.html",
                {"project": project, "active": "projects"},
                status_code=status.HTTP_201_CREATED,
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
async def api_import_project_file(project_id: str, request: Request, file: UploadFile | None = PROJECT_OPTIONAL_UPLOAD_FILE):
    try:
        await _project_service(request).get_project(project_id)
        body: dict[str, Any] = {}
        if file is not None:
            content = await file.read()
            stored = store_source_file(project_id, file.filename or "upload.csv", content)
        else:
            body = await _request_data(request)
            stored_info = _stored_file_from_body(body)
            stored = stored_source_file(
                project_id,
                str(stored_info.get("relative_path") or ""),
                original_filename=str(stored_info.get("original_filename") or "upload.csv"),
                sha256=str(stored_info.get("sha256") or ""),
                size_bytes=int(stored_info.get("size_bytes") or 0),
                file_format=str(stored_info.get("file_format") or "csv"),
            )
        response = await _import_stored_file(request, project_id, stored, body=body)
        if _is_hx(request):
            return templates.TemplateResponse(request, "project_import_result.html", response)
        return response
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/imports/preview")
async def api_preview_project_import(project_id: str, request: Request, file: UploadFile = PROJECT_UPLOAD_FILE):
    try:
        await _project_service(request).get_project(project_id)
        content = await file.read()
        stored = store_source_file(project_id, file.filename or "upload.csv", content)
        duplicate = await _project_service(request).source_file_exists(project_id, stored.sha256)
        preview = analyze_import_file(
            path=stored.absolute_path,
            original_filename=stored.original_filename,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            file_format=stored.file_format,
            duplicate=duplicate,
        )
        presets = await _project_service(request).list_mapping_presets(project_id)
        preset_items = [_preset_to_dict(preset) for preset in presets]
        suggested_preset = next(
            (preset for preset in preset_items if preset["header_fingerprint"] == preview.header_fingerprint),
            None,
        )
        response = {
            "project_id": project_id,
            "stored_file": {
                "original_filename": stored.original_filename,
                "relative_path": stored.relative_path,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "file_format": stored.file_format,
            },
            "preview": preview.to_dict(),
            "counts": _preview_error_counts(preview),
            "presets": preset_items,
            "suggested_preset": suggested_preset,
            "message": "Preview готов. Проверьте сопоставление колонок перед импортом.",
        }
        if _is_hx(request):
            return templates.TemplateResponse(
                request,
                "project_import_preview.html",
                {**response, "field_options": FIELD_OPTIONS},
            )
        return response
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/sample-imports/wb-cable-management")
async def api_import_wb_cable_management_sample(project_id: str, request: Request):
    try:
        await _project_service(request).get_project(project_id)
        content = _csv_bytes(WB_CABLE_MANAGEMENT_CANDIDATES)
        stored = store_source_file(project_id, "wb_cable_management_candidates.csv", content)
        response = await _import_stored_file(
            request,
            project_id,
            stored,
            body={"confirm_duplicate": True},
            allow_duplicate=True,
        )
        response["sample"] = "wb_cable_management"
        if _is_hx(request):
            return templates.TemplateResponse(request, "project_import_result.html", response)
        return response
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/market-analysis")
async def api_project_market_analysis(project_id: str, request: Request):
    try:
        project = await _project_service(request).get_project(project_id)
        body = await _request_data(request)
        marketplace = str(body.get("marketplace") or project.marketplace or "wildberries")
        max_results = int(body.get("max_results") or 12)
        analysis = await run_market_analysis(
            str(body.get("query") or ""),
            marketplace=marketplace,
            max_results=max_results,
        )
        rows = market_analysis_products_to_rows(analysis)
        if not rows:
            message = "Рынок ответил пустой выдачей. Попробуйте более широкий запрос или другой маркетплейс."
            if analysis.ozon_blocked_message:
                message = analysis.ozon_blocked_message + " Попробуйте Wildberries или Яндекс Маркет."
            response = {
                "status": "empty",
                "project_id": project_id,
                "query": analysis.query,
                "marketplace": analysis.marketplace,
                "executed_queries": analysis.executed_queries,
                "found_products": 0,
                "total_products": 0,
                "changed_products": 0,
                "errors": 0,
                "message": message,
            }
            if _is_hx(request):
                return templates.TemplateResponse(request, "project_market_analysis_result.html", response)
            return response

        filename = market_analysis_filename(analysis.query, analysis.marketplace)
        stored = store_source_file(project_id, filename, _csv_bytes(rows))
        response = await _import_stored_file(
            request,
            project_id,
            stored,
            body={"confirm_duplicate": True},
            allow_duplicate=True,
        )
        response.update(
            {
                "query": analysis.query,
                "marketplace": analysis.marketplace,
                "executed_queries": analysis.executed_queries,
                "found_products": analysis.found_count,
                "message": f"Анализ рынка нашёл {analysis.found_count} товаров и добавил их в проект.",
            }
        )
        if _is_hx(request):
            return templates.TemplateResponse(request, "project_market_analysis_result.html", response)
        return response
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/imports/error-report.csv")
async def api_project_import_error_report(project_id: str, request: Request):
    try:
        await _project_service(request).get_project(project_id)
        body = await _request_data(request)
        stored_info = _stored_file_from_body(body)
        stored = stored_source_file(
            project_id,
            str(stored_info.get("relative_path") or ""),
            original_filename=str(stored_info.get("original_filename") or "upload.csv"),
            sha256=str(stored_info.get("sha256") or ""),
            size_bytes=int(stored_info.get("size_bytes") or 0),
            file_format=str(stored_info.get("file_format") or "csv"),
        )
        preview = analyze_import_file(
            path=stored.absolute_path,
            original_filename=stored.original_filename,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            file_format=stored.file_format,
            duplicate=await _project_service(request).source_file_exists(project_id, stored.sha256),
            selected_sheet=body.get("selected_sheet"),
        )
        return _error_csv_response(project_id, preview)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.delete("/api/projects/{project_id}/import-presets/{preset_id}")
async def api_delete_import_preset(project_id: str, preset_id: str, request: Request):
    try:
        await _project_service(request).delete_mapping_preset(project_id, preset_id)
        return {"status": "deleted", "preset_id": preset_id}
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


@router.get("/api/projects/{project_id}/products/{product_id}/seo")
async def api_project_seo(project_id: str, product_id: int, request: Request):
    try:
        return await _effective_service(request).seo(project_id, product_id)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/products/{product_id}/semantic-core")
async def api_project_semantic_core(project_id: str, product_id: int, request: Request):
    """Возвращает семантическое ядро для effective snapshot. Не мутирует БД."""
    try:
        card = await _effective_service(request).get_effective_card(project_id, product_id)
        from app.effective_card.service import _unified_from_snapshot
        from app.semantic_core import build_semantic_core
        unified = _unified_from_snapshot(card.effective_snapshot, product_id)
        core = build_semantic_core(
            name=unified.name,
            description=unified.description,
            attributes=dict(unified.attributes) if unified.attributes else None,
            category=unified.category,
            tags=unified.tags,
            brand=unified.brand,
        )
        return {
            "project_id": project_id,
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
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/projects/{project_id}/products/{product_id}/semantic-core", response_class=HTMLResponse)
async def project_product_semantic_core_html(project_id: str, product_id: int, request: Request):
    """Возвращает HTML-фрагмент семантического ядра для HTMX."""
    try:
        card = await _effective_service(request).get_effective_card(project_id, product_id)
        from app.effective_card.service import _unified_from_snapshot
        from app.semantic_core import build_semantic_core
        unified = _unified_from_snapshot(card.effective_snapshot, product_id)
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
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/keywords/import")
async def api_import_keywords(project_id: str, request: Request, file: UploadFile | None = PROJECT_OPTIONAL_UPLOAD_FILE):
    """Импорт ключевых слов из CSV. Не мутирует БД -- только парсинг."""
    try:
        await _project_service(request).get_project(project_id)
        if file is None:
            raise HTTPException(status_code=400, detail="Загрузите CSV-файл с ключевыми словами.")
        content = await file.read()
        from app.keyword_sources import ManualCSVSource
        from app.products.schema import UnifiedProduct
        source = ManualCSVSource(content)
        product = UnifiedProduct(name="", source_id="", source_type="csv_import")
        keywords = source.get_keywords(product)
        return {"project_id": project_id, "keywords": keywords, "count": len(keywords)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/api/projects/{project_id}/products/{product_id}/seo-suggestions")
async def api_project_seo_suggestions(project_id: str, product_id: int, request: Request):
    """Preview SEO suggestions without mutating the approval queue."""
    try:
        suggestions = await _effective_service(request).seo_suggestions(project_id, product_id)
        return [_seo_suggestion_preview(product_id, suggestion) for suggestion in suggestions]
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/products/{product_id}/seo-suggestions")
async def api_queue_project_seo_suggestions(project_id: str, product_id: int, request: Request):
    """Queue factual SEO suggestions for the existing approval workflow."""
    try:
        form = await request.form()
        action = str(form.get("action", "")).strip()
        if not action:
            suggestions = await _effective_service(request).seo(project_id, product_id)
            recommendation_items = suggestions.get("effective", {}).get("recommendations", []) if isinstance(suggestions, dict) else []
            action = str(recommendation_items[0].get("action") if recommendation_items else "").strip()
        if not action:
            raise HTTPException(status_code=400, detail="SEO recommendation action is required")

        job = await request.app.state.db.create_job(
            "seo_ai_suggestions",
            {
                "project_id": project_id,
                "product_id": product_id,
                "action": action,
            },
        )
        logger.info(
            "SEO recommendation queued task_id=%s project_id=%s product_id=%s stage=queued",
            job.job_id,
            project_id,
            product_id,
        )
        try:
            result = await process_project_seo_suggestion_job(
                request.app,
                job.job_id,
                project_id,
                product_id,
                action=action,
            )
        except Exception as exc:
            error_text = str(exc).strip() or exc.__class__.__name__
            logger.info(
                "Suggestion returned to frontend task_id=%s project_id=%s product_id=%s stage=failed error=%s",
                job.job_id,
                project_id,
                product_id,
                error_text,
            )
            if _is_hx(request):
                return HTMLResponse(
                    '<div class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">'
                    f"Ошибка генерации AI: {error_text}. Job: {job.job_id}"
                    "</div>"
                )
            return {
                "success": False,
                "task_id": job.job_id,
                "status": "failed",
                "error": error_text,
                "queued": 0,
                "items": [],
            }
        queued_ids = set(result["approval_ids"])
        queued = [item for item in await _approval_queue(request).get_all() if item.approval_id in queued_ids]
        logger.info(
            "Suggestion returned to frontend task_id=%s project_id=%s product_id=%s queued=%s stage=completed",
            job.job_id,
            project_id,
            product_id,
            len(queued),
        )
        if _is_hx(request):
            return HTMLResponse(
                '<div class="rounded border border-green-200 bg-green-50 p-3 text-sm text-green-700">'
                f"Поставлено в согласование: {len(queued)}. Job: {job.job_id}"
                "</div>"
            )
        return {
            "success": True,
            "task_id": job.job_id,
            "status": result["status"],
            "model_used": result.get("model_used"),
            "queued": len(queued),
            "items": [_approval_to_dict(item) for item in queued],
        }
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


@router.get("/api/projects/{project_id}/products/{product_id}/versions")
async def api_project_product_versions(project_id: str, product_id: int, request: Request):
    try:
        project_product = await _project_service(request).get_project_product(project_id, product_id)
        versions = await ProductCardEditorService(request.app.state.db).list_persisted_versions(
            product_id,
            project_id=project_id,
            project_product_id=project_product.project_product_id,
            limit=100,
        )
        from app.web.routes.editor import _version_to_dict

        return {"project_id": project_id, "product_id": product_id, "items": [_version_to_dict(version) for version in versions]}
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/api/projects/{project_id}/products/{product_id}/versions/{version_number}/rollback")
async def api_project_rollback_version(project_id: str, product_id: int, version_number: int, request: Request):
    body = await _request_data(request)
    try:
        if not str(body.get("reason") or "").strip():
            raise ValueError("Укажите причину отката")
        project_product = await _project_service(request).get_project_product(project_id, product_id)
        result = await ProductCardEditorService(request.app.state.db).rollback_version(
            product_id,
            version_number,
            current_version_id=body.get("current_version_id"),
            actor_id="operator",
            reason=body.get("reason"),
            project_id=project_id,
            project_product_id=project_product.project_product_id,
        )
        from app.web.routes.editor import _version_to_dict

        response = {
            "version": _version_to_dict(result.version),
            "event": result.event.to_dict(),
            "diff": [item.to_dict() for item in result.diff],
        }
        if _is_hx(request):
            return templates.TemplateResponse(request, "project_action_result.html", {"result": response})
        return response
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/projects/{project_id}/products/{product_id}/manual-edit/preview", response_class=HTMLResponse)
async def project_manual_edit_preview(project_id: str, product_id: int, request: Request):
    body = await _request_data(request)
    card = await _effective_service(request).get_effective_card(project_id, product_id)
    payload = _editable_payload(body)
    after = {**card.effective_snapshot, **payload}
    diff = [
        {"field": key, "before": card.effective_snapshot.get(key), "after": after.get(key)}
        for key in sorted(set(card.effective_snapshot) | set(after))
        if card.effective_snapshot.get(key) != after.get(key)
    ]
    return templates.TemplateResponse(
        request,
        "project_manual_edit_preview.html",
        {
            "project_id": project_id,
            "product_id": product_id,
            "payload": payload,
            "diff": diff,
            "current_version_id": card.latest_version_id,
        },
    )


@router.post("/projects/{project_id}/products/{product_id}/manual-edit/apply", response_class=HTMLResponse)
async def project_manual_edit_apply(project_id: str, product_id: int, request: Request):
    body = await _request_data(request)
    try:
        project_product = await _project_service(request).get_project_product(project_id, product_id)
        payload = _editable_payload(body)
        service = ProductCardEditorService(request.app.state.db)
        draft = await service.create_draft(
            product_id,
            payload=payload,
            base_version_id=body.get("current_version_id"),
            actor_id="operator",
            comment=body.get("comment") or "Ручная правка через интерфейс проекта",
            project_id=project_id,
            project_product_id=project_product.project_product_id,
        )
        result = await service.apply_draft(
            product_id,
            draft.draft_id,
            revision=draft.revision,
            actor_id="operator",
            comment=body.get("comment") or "Ручная правка через интерфейс проекта",
            project_id=project_id,
            project_product_id=project_product.project_product_id,
        )
        return templates.TemplateResponse(
            request,
            "project_action_result.html",
            {"result": {"version": result.version.version_id, "diff": [item.to_dict() for item in result.diff]}},
        )
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
        _trace_request(request)
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


@router.post("/projects/{project_id}/exports", response_class=HTMLResponse)
async def project_create_export(project_id: str, request: Request):
    body = await _request_data(request)
    try:
        _trace_request(request)
        record = await ProjectExportService(request.app.state.db).create_export(
            project_id,
            file_format=body.get("file_format") or "csv",
            marketplace_profile=body.get("marketplace_profile") or "universal",
        )
        return _project_export_created_response(project_id, record)
    except Exception as exc:
        raise _editor_error(exc) from exc


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
        _trace_request(request)
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


@router.post("/projects/{project_id}/reports", response_class=HTMLResponse)
async def project_create_report(project_id: str, request: Request):
    body = await _request_data(request)
    try:
        _trace_request(request)
        record = await ClientDeliveryReportService(request.app.state.db).create_report(
            project_id,
            file_format=body.get("file_format") or "html",
        )
        return _project_report_created_response(project_id, record)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/projects/{project_id}/archive")
async def project_archive(project_id: str, request: Request):
    try:
        await _project_service(request).archive_project(project_id)
        return RedirectResponse(f"/projects/{project_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.post("/projects/{project_id}/full-archive")
async def project_create_full_archive(project_id: str, request: Request):
    try:
        result = await ProjectArchiveService(request.app.state.db).create_project_archive(project_id)
        return RedirectResponse(
            f"/projects/{project_id}/archives/{Path(result['relative_path']).name}/download",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        raise _editor_error(exc) from exc


@router.get("/projects/{project_id}/exports/{export_id}/download")
async def download_project_export(project_id: str, export_id: str, request: Request):
    async with request.app.state.db.session() as session:
        record = await session.scalar(
            select(ProjectExport)
            .where(ProjectExport.project_id == project_id)
            .where(ProjectExport.export_id == export_id)
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Экспорт не найден")
        return _download_project_artifact(project_id, record.relative_path)


@router.get("/projects/{project_id}/reports/{report_id}/download")
async def download_project_report(project_id: str, report_id: str, request: Request):
    async with request.app.state.db.session() as session:
        record = await session.scalar(
            select(ProjectReport)
            .where(ProjectReport.project_id == project_id)
            .where(ProjectReport.report_id == report_id)
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        return _download_project_artifact(project_id, record.relative_path)


@router.get("/projects/{project_id}/archives/{filename}/download")
async def download_project_archive(project_id: str, filename: str):
    return _download_project_artifact(project_id, f"archives/{Path(filename).name}")


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


@router.get("/projects/{project_id}/market-analysis", response_class=HTMLResponse)
async def project_market_analysis_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    return templates.TemplateResponse(
        request,
        "project_market_analysis.html",
        {"project": project, "active": "projects"},
    )


@router.get("/projects/{project_id}/products", response_class=HTMLResponse)
async def project_products_page(project_id: str, request: Request):
    project = await _project_service(request).get_project(project_id)
    products_with_seo = await _effective_service(request).list_effective_cards_with_seo_summary(project_id)
    return templates.TemplateResponse(
        request,
        "project_products.html",
        {"project": project, "products": products_with_seo, "active": "projects"},
    )


@router.get("/projects/{project_id}/products/{product_id}", response_class=HTMLResponse)
async def project_product_detail_page(project_id: str, product_id: int, request: Request):
    from app.competitor_analysis.store import CompetitorSnapshotStore
    from app.content_pipeline.artifact_store import ArtifactStore

    project = await _project_service(request).get_project(project_id)
    service = _effective_service(request)
    card = await service.get_effective_card(project_id, product_id)
    seo = await service.seo(project_id, product_id)

    artifact_store = ArtifactStore(request.app.state.db)
    content_strategy = await artifact_store.get_latest(
        project_id=project_id, project_product_id=card.project_product_id, artifact_type="content_strategy"
    )
    quality_report = await artifact_store.get_latest(
        project_id=project_id, project_product_id=card.project_product_id, artifact_type="quality_report"
    )
    competitors = await CompetitorSnapshotStore(request.app.state.db).get_latest_batch(
        project_id=project_id, project_product_id=card.project_product_id
    )
    return templates.TemplateResponse(
        request,
        "project_product_detail.html",
        {
            "project": project,
            "card": card,
            "seo": seo["effective"],
            "active": "projects",
            "content_strategy": ArtifactStore.payload_dict(content_strategy) if content_strategy else None,
            "quality_report": ArtifactStore.payload_dict(quality_report) if quality_report else None,
            "competitors": competitors,
        },
    )


@router.get("/projects/{project_id}/products/{product_id}/edit", response_class=HTMLResponse)
async def project_product_edit_page(project_id: str, product_id: int, request: Request):
    project = await _project_service(request).get_project(project_id)
    card = await _effective_service(request).get_effective_card(project_id, product_id)
    return templates.TemplateResponse(
        request,
        "project_product_edit.html",
        {"project": project, "card": card, "active": "projects"},
    )


@router.get("/projects/{project_id}/products/{product_id}/versions", response_class=HTMLResponse)
async def project_product_versions_page(project_id: str, product_id: int, request: Request):
    project = await _project_service(request).get_project(project_id)
    card = await _effective_service(request).get_effective_card(project_id, product_id)
    project_product = await _project_service(request).get_project_product(project_id, product_id)
    versions = await ProductCardEditorService(request.app.state.db).list_persisted_versions(
        product_id,
        project_id=project_id,
        project_product_id=project_product.project_product_id,
        limit=100,
    )
    return templates.TemplateResponse(
        request,
        "project_product_versions.html",
        {"project": project, "card": card, "versions": versions, "active": "projects"},
    )


@router.get("/projects/{project_id}/reports", response_class=HTMLResponse)
async def project_reports_page(project_id: str, request: Request, created: str | None = Query(None)):
    project = await _project_service(request).get_project(project_id)
    report = await ClientDeliveryReportService(request.app.state.db).preview(project_id)
    reports = await ClientDeliveryReportService(request.app.state.db).list_reports(project_id)
    created_report = await _project_report_by_id(request, project_id, created) if created else None
    return templates.TemplateResponse(
        request,
        "project_reports.html",
        {
            "project": project,
            "report": report,
            "reports": reports,
            "created": created_report,
            "active": "projects",
        },
    )


@router.get("/projects/{project_id}/exports", response_class=HTMLResponse)
async def project_exports_page(project_id: str, request: Request, created: str | None = Query(None)):
    project = await _project_service(request).get_project(project_id)
    exports = await ProjectExportService(request.app.state.db).list_exports(project_id)
    created_export = await _project_export_by_id(request, project_id, created) if created else None
    return templates.TemplateResponse(
        request,
        "project_exports.html",
        {
            "project": project,
            "exports": exports,
            "created": created_export,
            "active": "projects",
        },
    )


def _editable_payload(body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in ("title", "description", "brand", "availability"):
        if field in body:
            payload[field] = str(body.get(field) or "").strip()
    if "price" in body:
        raw_price = str(body.get("price") or "").strip()
        payload["price"] = int(float(raw_price.replace(",", "."))) if raw_price else None
    if "selling_points" in body:
        raw_points = body.get("selling_points") or ""
        payload["selling_points"] = [item.strip() for item in str(raw_points).split("\n") if item.strip()]
    return payload


def _download_project_artifact(project_id: str, relative_path: str) -> FileResponse:
    root = project_root(project_id)
    target = root / relative_path
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if root_resolved not in target_resolved.parents:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if not target_resolved.exists() or not target_resolved.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(target_resolved, filename=target_resolved.name)


def _project_export_created_response(project_id: str, record: ProjectExport):
    return RedirectResponse(
        url=f"/projects/{project_id}/exports?created={record.export_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _project_report_created_response(project_id: str, record: ProjectReport):
    return RedirectResponse(
        url=f"/projects/{project_id}/reports?created={record.report_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _project_export_by_id(request: Request, project_id: str, export_id: str):
    async with request.app.state.db.session() as session:
        return await session.scalar(
            select(ProjectExport)
            .where(ProjectExport.project_id == project_id)
            .where(ProjectExport.export_id == export_id)
        )


async def _project_report_by_id(request: Request, project_id: str, report_id: str):
    async with request.app.state.db.session() as session:
        return await session.scalar(
            select(ProjectReport)
            .where(ProjectReport.project_id == project_id)
            .where(ProjectReport.report_id == report_id)
        )
