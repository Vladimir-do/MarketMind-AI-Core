from __future__ import annotations

import csv
import io
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.web.app import templates
from app.web.schemas import ImportResult

router = APIRouter()

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"

TEMPLATE_HEADERS = [
    "название", "бренд", "цена", "старая цена", "скидка",
    "описание", "категория", "артикул", "вес", "ширина", "высота",
    "глубина", "фото", "валюта",
]


async def _save_products_to_db(request: Request, products: list) -> int:
    """Save UnifiedProduct list to DB via db.save_product. Returns count saved."""
    db = request.app.state.db
    saved = 0
    for p in products:
        url = p.source_url or f"file://import/{p.source_id}"
        data = {
            "name": p.name,
            "price": p.price,
            "image_url": p.image_urls[0] if p.image_urls else None,
            "availability": "in_stock",
        }
        await db.save_product(url, data)
        saved += 1
    return saved


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

        saved = await _save_products_to_db(request, [ep.product for ep in result.enriched])

        return ImportResult(
            task_id=uuid.uuid4().hex[:12],
            status="completed",
            total_products=saved,
            errors=len(result.errors),
            message=f"Импортировано и сохранено {saved} товаров, ошибок: {len(result.errors)}",
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


@router.get("/api/import/template/csv")
async def download_csv_template():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_HEADERS)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="template_products.csv"'},
    )


@router.get("/api/import/template/xlsx")
async def download_xlsx_template():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Товары"
    ws.append(TEMPLATE_HEADERS)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_products.xlsx"'},
    )


@router.post("/api/import/demo", response_model=ImportResult)
async def load_demo_data(request: Request):
    csv_path = SAMPLES_DIR / "products_demo.csv"
    if not csv_path.exists():
        return ImportResult(
            task_id=uuid.uuid4().hex[:12],
            status="failed",
            total_products=0,
            errors=1,
            message=f"Демо-файл не найден: {csv_path}",
        )

    from app.pipeline import ImportPipeline

    pipeline = ImportPipeline()
    result = pipeline.run_file(csv_path)

    saved = await _save_products_to_db(request, [ep.product for ep in result.enriched])

    return ImportResult(
        task_id=uuid.uuid4().hex[:12],
        status="completed",
        total_products=saved,
        errors=len(result.errors),
        message=f"Загружено {saved} демо-товаров, ошибок: {len(result.errors)}",
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    return templates.TemplateResponse(request, "import_.html")
