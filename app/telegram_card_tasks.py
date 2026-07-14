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


def build_card_task_from_product(product: Any, price: int | None) -> str:
    lines = [
        f"{PRODUCT_LABEL}: {product.name or NEW_PRODUCT}",
        NO_BRAND,
    ]
    if price:
        lines.append(f"{PRICE_LABEL}: {price}")
    if product.image_url:
        lines.append(product.image_url)
    lines.append(f"{SOURCE_LABEL}: {product.url}")
    return "\n".join(lines)


def build_card_task_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    slug = ""
    if "product" in parts:
        idx = parts.index("product")
        if idx + 1 < len(parts):
            slug = parts[idx + 1]
    if not slug and parts:
        slug = parts[-1]

    slug = unquote(slug)
    slug = re.sub(r"-\d{6,}$", "", slug)
    title = re.sub(r"[-_]+", " ", slug).strip()
    title = re.sub(r"\s+", " ", title)
    title = title[:1].upper() + title[1:] if title else NEW_PRODUCT
    return "\n".join([
        f"{PRODUCT_LABEL}: {title}",
        NO_BRAND,
        f"{SOURCE_LABEL}: {url}",
        URL_RECOVERY_NOTE,
    ])
