from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

PRODUCT_LABEL = "\u0442\u043e\u0432\u0430\u0440"
NEW_PRODUCT = "\u041d\u043e\u0432\u044b\u0439 \u0442\u043e\u0432\u0430\u0440"
NO_BRAND = "\u0431\u0440\u0435\u043d\u0434: \u041d\u0435\u0442 \u0431\u0440\u0435\u043d\u0434\u0430"
PRICE_LABEL = "\u0446\u0435\u043d\u0430"
SOURCE_LABEL = "\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a"
URL_RECOVERY_NOTE = (
    "\u043f\u0440\u0438\u043c\u0435\u0447\u0430\u043d\u0438\u0435: "
    "\u0414\u0430\u043d\u043d\u044b\u0435 \u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u044b "
    "\u0438\u0437 \u0441\u0441\u044b\u043b\u043a\u0438, \u043f\u043e\u0442\u043e\u043c\u0443 "
    "\u0447\u0442\u043e \u043c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441 "
    "\u043d\u0435 \u043e\u0442\u0434\u0430\u043b \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443. "
    "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0432\u0440\u0443\u0447\u043d\u0443\u044e."
)


def extract_ozon_product_identity(url: str) -> tuple[str | None, str | None]:
    """Return a conservative title-from-slug and Ozon product ID from a URL."""
    parsed = urlparse(url or "")
    if "ozon.ru" not in (parsed.netloc or "").lower():
        return None, None
    parts = [part for part in parsed.path.split("/") if part]
    if "product" not in parts:
        return None, None
    idx = parts.index("product")
    if idx + 1 >= len(parts):
        return None, None
    slug = unquote(parts[idx + 1])
    id_match = re.search(r"-(\d{6,})$", slug)
    product_id = id_match.group(1) if id_match else None
    if id_match:
        slug = slug[:id_match.start()]
    title = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", slug)).strip()
    if title:
        title = title[:1].upper() + title[1:]
    return title or None, product_id


def build_card_task_from_product(product: Any, price: int | None) -> str:
    url_title, ozon_id = extract_ozon_product_identity(getattr(product, "url", ""))
    lines = [
        f"{PRODUCT_LABEL}: {product.name or url_title or NEW_PRODUCT}",
        NO_BRAND,
    ]
    if ozon_id:
        lines.append(f"артикул Ozon: {ozon_id}")
    if url_title and not price and not getattr(product, "image_url", None):
        lines.append("примечание: название восстановлено из URL, не подтверждено страницей товара; проверить вручную")
    if price:
        lines.append(f"{PRICE_LABEL}: {price}")
    elif url_title and (product.name or "").strip() == url_title:
        lines.append("примечание: название восстановлено из URL, не подтверждено страницей товара; проверить вручную")
    if product.image_url:
        lines.append(product.image_url)
    lines.append(f"{SOURCE_LABEL}: {product.url}")
    return "\n".join(lines)


def build_card_task_from_url(url: str) -> str:
    title, ozon_id = extract_ozon_product_identity(url)
    if not title:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        slug = unquote(parts[-1]) if parts else ""
        slug = re.sub(r"-\d{6,}$", "", slug)
        title = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", slug)).strip()
        title = title[:1].upper() + title[1:] if title else NEW_PRODUCT
    lines = [f"{PRODUCT_LABEL}: {title}", NO_BRAND]
    if ozon_id:
        lines.append(f"артикул Ozon: {ozon_id}")
    lines.extend([f"{SOURCE_LABEL}: {url}", URL_RECOVERY_NOTE])
    return "\n".join(lines)
