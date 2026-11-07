"""Marketplace result formatting and competitor search helpers for Telegram bot."""

import html

from app.parsers.router import search_all_marketplaces
from app.searcher import ozon_search_blocked_message

MARKETPLACE_LABELS = {
    "wildberries": ("🟣", "Wildberries"),
    "ozon": ("🔵", "Ozon"),
    "yandex_market": ("🟡", "Yandex Market"),
}


def _marketplace_result_count(results_by_marketplace: dict[str, list]) -> int:
    return sum(len(items) for items in results_by_marketplace.values())


def _first_marketplace_product(results_by_marketplace: dict[str, list], preferred: tuple[str, ...] = ()):
    ordered = [*preferred, "wildberries", "ozon", "yandex_market"]
    seen = set()
    for marketplace in ordered:
        if marketplace in seen:
            continue
        seen.add(marketplace)
        for product in results_by_marketplace.get(marketplace, []):
            if product:
                return product
    return None


def _format_cross_marketplace_results(
    results_by_marketplace: dict[str, list],
    *,
    title: str,
    empty_message: str,
) -> str:
    if not _marketplace_result_count(results_by_marketplace):
        return empty_message

    lines = [f"<b>{html.escape(title)}</b>"]
    for marketplace in ("wildberries", "ozon", "yandex_market"):
        items = results_by_marketplace.get(marketplace, [])
        if not items:
            continue
        emoji, label = MARKETPLACE_LABELS.get(marketplace, ("⚪", marketplace))
        lines.append(f"\n{emoji} <b>{label}</b>")
        for i, product in enumerate(items, 1):
            name = html.escape((product.name or "товар")[:90])
            url = html.escape(product.url or "")
            price_str = f"{product.price} ₽" if product.price is not None else "цена не определена"
            availability = product.availability or "наличие не определено"
            lines.append(f"{i}. <a href='{url}'>{name}</a>\n   💰 {price_str} · {html.escape(availability)}")
    lines.append("\n💡 Чтобы добавить товар в мониторинг, пришлите его ссылку.")
    return "\n".join(lines)


def build_competitor_search_status(query: str) -> str:
    """Tell the user which sources are searched when Ozon is cooling down."""
    blocked_message = ozon_search_blocked_message()
    safe_query = html.escape(query)
    if blocked_message:
        return (
            f"🔎 {html.escape(blocked_message)} "
            "Ищу альтернативы на Wildberries и Яндекс Маркете "
            f"для карточки: <b>{safe_query}</b>..."
        )
    return f"🔎 Ищу конкурентов для карточки: <b>{safe_query}</b>..."


def _flatten_competitor_results(results_by_marketplace: dict[str, list]) -> list[dict]:
    items: list[dict] = []
    for marketplace in ("wildberries", "ozon", "yandex_market"):
        for product in results_by_marketplace.get(marketplace, []):
            if not product:
                continue
            if hasattr(product, "to_dict"):
                data = product.to_dict()
            elif isinstance(product, dict):
                data = dict(product)
            else:
                continue
            data.setdefault("marketplace", marketplace)
            items.append(data)
    return items


async def _search_competitors_with_fallback(query: str, max_per_site: int = 5) -> list[dict]:
    blocked_message = ozon_search_blocked_message()
    exclude = ("ozon",) if blocked_message else ()
    all_results = await search_all_marketplaces(query, max_per_site=max_per_site, exclude_marketplaces=exclude)
    return _flatten_competitor_results(all_results)
