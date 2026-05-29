import re
from html import escape
from dataclasses import dataclass, field
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup


@dataclass(slots=True)
class FunPayOffer:
    url: str
    category: str | None = None
    title: str | None = None
    seller: str | None = None
    seller_reviews: str | None = None
    price_rub: float | None = None
    params: dict[str, str] = field(default_factory=dict)
    short_description: str | None = None
    full_description: str | None = None


def is_funpay_offer_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    return host.endswith("funpay.com") and parsed.path.rstrip("/") == "/lots/offer"


def parse_funpay_offer_html(html: str, url: str) -> FunPayOffer:
    soup = BeautifulSoup(html, "lxml")
    params: dict[str, str] = {}

    for item in soup.select(".param-list .param-item"):
        label = item.select_one("h5")
        if not label:
            continue
        key = _clean_text(label.get_text(" ", strip=True))
        label.extract()
        value = _clean_text(item.get_text(" ", strip=True))
        if key and value:
            params[key] = value

    short_description = params.get("Краткое описание")
    full_description = params.get("Подробное описание")
    category_elem = soup.select_one(".back-link .inside")
    seller_elem = soup.select_one(".media-user-name a")
    seller_reviews_elem = soup.select_one(".seller-promo-desc")

    return FunPayOffer(
        url=url,
        category=_clean_text(category_elem.get_text(" ", strip=True)) if category_elem else None,
        title=_build_title(params, short_description),
        seller=_clean_text(seller_elem.get_text(" ", strip=True)) if seller_elem else None,
        seller_reviews=_clean_text(seller_reviews_elem.get_text(" ", strip=True)) if seller_reviews_elem else None,
        price_rub=_extract_price_rub(soup),
        params=params,
        short_description=short_description,
        full_description=full_description,
    )


async def fetch_funpay_offer(url: str, timeout: int = 20) -> FunPayOffer:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            html = await response.text()
    return parse_funpay_offer_html(html, url)


def build_funpay_search_query(offer: FunPayOffer) -> str:
    description = offer.short_description or offer.title or ""
    subscription_type = offer.params.get("Тип подписки")
    duration = _extract_duration(description)

    if offer.category and "chatgpt" in offer.category.lower():
        pieces = ["ChatGPT"]
        if subscription_type:
            pieces.append(subscription_type)
        pieces.append("подписка")
        if duration:
            pieces.append(duration)
        return " ".join(pieces)

    pieces = []
    if offer.category:
        pieces.append(offer.category)

    if subscription_type:
        pieces.append(subscription_type)

    if description:
        pieces.append(_trim_noise(description))

    query = " ".join(piece for piece in pieces if piece)
    query = re.sub(r"\s+", " ", query).strip()
    return query[:160] if query else (offer.category or "ChatGPT Plus")


def format_funpay_offer_summary(offer: FunPayOffer, query: str) -> str:
    lines = ["<b>FunPay оффер распознан</b>"]
    if offer.category:
        lines.append(f"Категория: <b>{escape(offer.category)}</b>")
    if offer.title:
        lines.append(f"Описание: {escape(offer.title[:180])}")
    if offer.price_rub is not None:
        lines.append(f"Цена FunPay: <b>{offer.price_rub:g} ₽</b>")
    if offer.seller:
        seller = escape(offer.seller)
        if offer.seller_reviews:
            seller += f" ({escape(offer.seller_reviews)})"
        lines.append(f"Продавец: {seller}")
    lines.append(f"\nИщу аналог на Ozon по запросу: <b>{escape(query)}</b>")
    return "\n".join(lines)


def _build_title(params: dict[str, str], short_description: str | None) -> str | None:
    if short_description:
        return short_description
    title_bits = []
    for key in ("Тип подписки", "Способ получения", "Была подписка"):
        value = params.get(key)
        if value:
            title_bits.append(value)
    return " ".join(title_bits) or None


def _extract_price_rub(soup: BeautifulSoup) -> float | None:
    prices = []
    for option in soup.select("option[data-cy='rub']"):
        factors = option.get("data-factors", "")
        first_factor = factors.split(",", 1)[0].strip()
        if first_factor:
            try:
                prices.append(float(first_factor))
                continue
            except ValueError:
                pass
        text = option.get("data-content", "") or option.get_text(" ", strip=True)
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*₽", text)
        if match:
            prices.append(float(match.group(1).replace(",", ".")))
    return min(prices) if prices else None


def _trim_noise(text: str) -> str:
    text = re.sub(r"[^\w\s+.-]", " ", text, flags=re.UNICODE)
    text = re.sub(
        r"\b(гарантии|любой|аккаунт|акк|дней|ваш|вашего|месяц|на|к|для)\b",
        " ",
        text,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_duration(text: str) -> str | None:
    lowered = text.lower()
    month_match = re.search(r"(\d+)\s*(?:месяц|мес)", lowered)
    if month_match:
        return f"{month_match.group(1)} месяц"
    days_match = re.search(r"(\d+)\s*(?:день|дня|дней)", lowered)
    if days_match:
        days = int(days_match.group(1))
        if 28 <= days <= 31:
            return "1 месяц"
        return f"{days} дней"
    return None
