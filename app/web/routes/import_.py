from __future__ import annotations

import csv
import io
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.web.app import templates
from app.web.image_urls import displayable_image_url
from app.web.schemas import ImportResult

router = APIRouter()

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"

TEMPLATE_HEADERS = [
    "название",
    "бренд",
    "цена",
    "старая цена",
    "скидка",
    "описание",
    "категория",
    "артикул",
    "вес",
    "ширина",
    "высота",
    "глубина",
    "фото",
    "валюта",
]


async def _save_products_to_db(request: Request, products: list) -> int:
    """Save UnifiedProduct list to DB via db.save_product. Returns count saved."""
    db = request.app.state.db
    saved = 0
    for p in products:
        url = p.source_url or f"file://import/{p.source_id}"
        image_url = p.thumbnail_url or (p.image_urls[0] if p.image_urls else None)
        data = {
            "name": p.name,
            "price": p.price,
            "image_url": displayable_image_url(image_url),
            "availability": "in_stock",
        }
        await db.save_product(url, data)
        saved += 1
    return saved


async def _recent_import_products(request: Request, limit: int = 8) -> list[dict]:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return []

    products = await db.get_all_products()
    products = sorted(products, key=lambda p: (p.last_check is not None, p.last_check, p.id), reverse=True)

    items = []
    for product in products[:limit]:
        last_price = await db.get_last_price(product.id)
        items.append(
            {
                "id": product.id,
                "name": product.name or "Без названия",
                "url": product.url,
                "price": last_price.price if last_price else None,
                "availability": last_price.availability_status if last_price else "unknown",
                "last_check": product.last_check,
            }
        )
    return items


def _wants_html(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _import_result_response(request: Request, result: ImportResult, *, error: bool = False):
    if _wants_html(request):
        return templates.TemplateResponse(request, "import_result.html", {"result": result})
    if error:
        return JSONResponse(status_code=422, content=result.model_dump())
    return result


def _template_base_context() -> dict:
    from app.runtime_paths import runtime_banner

    return {"runtime_banner": templates.env.globals.get("runtime_banner") or runtime_banner()}


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

        return _import_result_response(
            request,
            ImportResult(
                task_id=uuid.uuid4().hex[:12],
                status="completed",
                total_products=saved,
                errors=len(result.errors),
                message=f"Импортировано и сохранено {saved} товаров, ошибок: {len(result.errors)}",
            ),
        )
    except Exception as exc:
        return _import_result_response(
            request,
            ImportResult(
                task_id=uuid.uuid4().hex[:12],
                status="failed",
                total_products=0,
                errors=1,
                message=f"Ошибка импорта: {exc}",
            ),
            error=True,
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
        return _import_result_response(
            request,
            ImportResult(
                task_id=uuid.uuid4().hex[:12],
                status="failed",
                total_products=0,
                errors=1,
                message=f"Демо-файл не найден: {csv_path}",
            ),
        )

    from app.pipeline import ImportPipeline

    pipeline = ImportPipeline()
    result = pipeline.run_file(csv_path)

    saved = await _save_products_to_db(request, [ep.product for ep in result.enriched])

    return _import_result_response(
        request,
        ImportResult(
            task_id=uuid.uuid4().hex[:12],
            status="completed",
            total_products=saved,
            errors=len(result.errors),
            message=f"Загружено {saved} демо-товаров, ошибок: {len(result.errors)}",
        ),
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    products = await _recent_import_products(request)
    db = getattr(request.app.state, "db", None)
    total_products = len(await db.get_all_products()) if db is not None else 0
    return templates.TemplateResponse(
        request,
        "import_.html",
        {**_template_base_context(), "products": products, "total_products": total_products},
    )
