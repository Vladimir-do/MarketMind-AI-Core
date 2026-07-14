import re
from urllib.parse import parse_qs, urlparse

from app.utils.urls import is_yandex_market_url


def validate_search_query(query: str) -> tuple[bool, str | None]:
    parsed = urlparse(query.strip())
    if parsed.scheme not in {"http", "https"}:
        return True, None

    host = (parsed.netloc or "").lower()
    if "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(query):
        if not is_supported_marketplace_url(query):
            return False, (
                "Это страница маркетплейса, а не ссылка на конкретный товар. "
                "Пришлите ссылку на карточку товара или обычное название товара."
            )
        return False, (
            "Это ссылка на товар. Для ссылок используйте /add, "
            "а для /search отправьте обычное название товара."
        )
    return False, (
        f"Это ссылка на неподдерживаемый сайт ({host or 'unknown'}). "
        "Сейчас я ищу только по названию товара на Ozon. "
        "Пришлите название, например: <code>держатель для телефона</code>."
    )


def extract_urls(text: str) -> list[str]:
    return [url.rstrip(".,);]}>") for url in re.findall(r"https?://\S+", text or "", flags=re.I)]


def is_supported_marketplace_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "ozon.ru" in host:
        return "/product/" in path
    if "wildberries.ru" in host or "wb.ru" in host:
        query = parse_qs(parsed.query)
        if any(re.fullmatch(r"\d{6,12}", value) for key in ("nm", "nm_id", "nmId") for value in query.get(key, [])):
            return True
        return bool(re.search(r"(?:^|/)catalog/\d{6,12}(?:/|$)", path))
    return is_yandex_market_url(url)


def extract_supported_urls(text: str) -> list[str]:
    return [url for url in extract_urls(text) if is_supported_marketplace_url(url)]


def extract_command_payload(text: str | None, command: str) -> str:
    match = re.match(rf"^/{re.escape(command)}(?:@\w+)?(?:\s+(.*))?$", text or "", flags=re.I | re.S)
    return (match.group(1) or "").strip() if match else ""
