from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.web.app import templates
from app.web.schemas import ImportResult

router = APIRouter()


@router.post("/api/import/file", response_model=ImportResult)
async def import_file(request: Request, file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.csv").suffix or ".csv"
    tmp = Path(tempfile.gettempdir()) / f"web_import_{uuid.uuid4().hex}{suffix}"
    try:
        content = await file.read()
        tmp.write_bytes(content)

        from app.pipeline import ImportPipeline

        pipeline = ImportPipeline()
        result = pipeline.run_file(tmp)

        return ImportResult(
            task_id=uuid.uuid4().hex[:12],
            status="completed",
            total_products=len(result.enriched),
            errors=len(result.errors),
            message=f"Импортировано {len(result.enriched)} товаров, ошибок: {len(result.errors)}",
        )
    except Exception as exc:
        return ImportResult(
            task_id=uuid.uuid4().hex[:12],
            status="failed",
            total_products=0,
            errors=1,
            message=f"Ошибка импорта: {exc}",
        )
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    return templates.TemplateResponse(request, "import_.html")
