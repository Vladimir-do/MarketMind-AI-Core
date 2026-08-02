from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.web.app import templates
from app.web.schemas import ProductListItem

router = APIRouter()


def _detect_marketplace(url: str) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low or "yandex.ru/market" in low:
        return "yandex_market"
    return "unknown"


def _product_to_item(product, last_price) -> ProductListItem:
    return ProductListItem(
        id=product.id,
        name=product.name or "—",
        url=product.url,
        marketplace=_detect_marketplace(product.url),
        current_price=last_price.price if last_price else None,
        availability=last_price.availability_status if last_price else "unknown",
        last_check=product.last_check.isoformat() if product.last_check else None,
    )


@router.get("/api/products", response_model=list[ProductListItem])
async def list_products(
    request: Request,
    q: str | None = Query(None, description="Search by name"),
):
    db = request.app.state.db
    products = await db.get_all_products()

    items = []
    for p in products:
        last_price = await db.get_last_price(p.id)
        item = _product_to_item(p, last_price)
        if q and q.lower() not in (item.name or "").lower():
            continue
        items.append(item)
    return items


@router.get("/products", response_class=HTMLResponse)
async def products_page(request: Request, q: str | None = None):
    db = request.app.state.db
    products = await db.get_all_products()

    items = []
    for p in products:
        last_price = await db.get_last_price(p.id)
        item = _product_to_item(p, last_price)
        if q and q.lower() not in (item.name or "").lower():
            continue
        items.append(item)

    return templates.TemplateResponse(
        request,
        "products.html",
        {"products": items, "q": q or ""},
    )
