from __future__ import annotations

import csv
import asyncio
import io
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

from app.task_intents import StructuredTask
from app.universal_parsing_core.parsers.universal_html import UniversalHtmlParser


logger = logging.getLogger(__name__)

DEFAULT_FIELDS = ("title", "price", "availability", "rating", "product_url")
DETAIL_FIELDS = frozenset(("upc", "product_type", "tax", "number_of_reviews", "description"))
SUPPORTED_FIELDS = frozenset((*DEFAULT_FIELDS, *DETAIL_FIELDS, "image_url", "url", "name", "entity_type", "source"))
RATING_WORDS = {"One", "Two", "Three", "Four", "Five"}
DEFAULT_DISCOVERY_LIMIT = 12


class ScrapingError(RuntimeError):
    """Raised when the generic scraper cannot produce a valid result."""


@dataclass(frozen=True, slots=True)
class ScrapeMetrics:
    url: str
    http_status: int
    bytes_received: int
    records: int
    pages_fetched: int = 1
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    records: list[dict[str, str]]
    fields: list[str]
    csv_bytes: bytes
    filename: str
    metrics: ScrapeMetrics


@dataclass(slots=True)
class ValidationReport:
    ok: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PageFetch:
    url: str
    http_status: int
    html_text: str


async def run_scraping_task(task: StructuredTask) -> ScrapeResult:
    if not task.target_url:
        raise ScrapingError("Target URL is missing.")

    fields = normalize_fields(task.fields)
    follow_pagination = bool(task.parameters.get("pagination") or task.parameters.get("scope") == "all_pages")
    delay_seconds = _delay_seconds_for(task)
    max_pages = int(task.parameters.get("max_pages") or 50)
    detail_concurrency = int(task.parameters.get("detail_concurrency") or 5)
    focus_terms = _focus_terms_for(task)
    fetcher = fetch_html_browser if _should_use_browser_fetch(task) else fetch_html
    logger.info(
        "Generic scraping started: url=%s fields=%s pagination=%s delay=%s max_pages=%s focus_terms=%s fetcher=%s",
        task.target_url,
        fields,
        follow_pagination,
        delay_seconds,
        max_pages,
        focus_terms,
        "browser" if fetcher is fetch_html_browser else "html",
    )
    pages = await fetch_page_sequence(
        task.target_url,
        follow_pagination=follow_pagination,
        delay_seconds=delay_seconds,
        max_pages=max_pages,
        fetcher=fetcher,
    )
    records: list[dict[str, str]] = []
    for page in pages:
        records.extend(extract_records_adaptive(page.html_text, page.url, fields, focus_terms=focus_terms))
    if not records:
        records.extend(
            await extract_records_from_discovered_pages(
                pages,
                fields,
                focus_terms=focus_terms,
                delay_seconds=delay_seconds,
                max_links=int(task.parameters.get("max_discovery_links") or DEFAULT_DISCOVERY_LIMIT),
                fetcher=fetcher,
            )
        )
    if _needs_detail_pages(fields):
        await enrich_records_from_detail_pages(
            records,
            fields,
            delay_seconds=delay_seconds,
            concurrency=detail_concurrency,
            fetcher=fetcher,
        )
    validation = validate_records(records, fields)
    if not validation.ok:
        raise ScrapingError("; ".join(validation.warnings) or "Validation failed.")

    csv_bytes = export_csv(records, fields)
    filename = build_csv_filename(task.target_url)
    metrics = ScrapeMetrics(
        url=task.target_url,
        http_status=pages[-1].http_status,
        bytes_received=sum(len(page.html_text.encode("utf-8", errors="ignore")) for page in pages),
        records=len(records),
        pages_fetched=len(pages),
        warnings=tuple(validation.warnings),
    )
    logger.info(
        "Generic scraping finished: url=%s status=%s pages=%s records=%s bytes=%s",
        metrics.url,
        metrics.http_status,
        metrics.pages_fetched,
        metrics.records,
        metrics.bytes_received,
    )
    return ScrapeResult(records=records, fields=fields, csv_bytes=csv_bytes, filename=filename, metrics=metrics)


def _should_use_browser_fetch(task: StructuredTask) -> bool:
    return bool(
        task.parameters.get("browser_fallback")
        or task.parameters.get("use_browser")
        or task.parameters.get("next_strategy") == "browser"
    )


def normalize_fields(fields: list[str] | tuple[str, ...] | None) -> list[str]:
    requested = list(fields or DEFAULT_FIELDS)
    normalized: list[str] = []
    for field in requested:
        key = (field or "").strip().lower().replace(" ", "_")
        if key == "url":
            key = "product_url"
        if key == "name":
            key = "title"
        if key in SUPPORTED_FIELDS and key not in normalized:
            normalized.append(key)
    return normalized or list(DEFAULT_FIELDS)


def _needs_detail_pages(fields: list[str] | tuple[str, ...]) -> bool:
    return any(field in DETAIL_FIELDS for field in fields)


async def fetch_html(url: str, timeout_seconds: float = 20.0) -> tuple[int, str]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {
        "User-Agent": "parser-agent-generic-scraper/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return response.status, await response.text(errors="replace")
    except aiohttp.ClientError as exc:
        logger.warning("Generic scraper network error: url=%s error=%s", url, exc)
        raise ScrapingError(f"Could not fetch page: {exc}") from exc
    except TimeoutError as exc:
        logger.warning("Generic scraper timeout: url=%s", url)
        raise ScrapingError("Page fetch timed out.") from exc


async def fetch_html_browser(url: str, timeout_seconds: float = 30.0) -> tuple[int, str]:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise ScrapingError("Browser fallback is unavailable: playwright is not installed.") from exc

    browser = None
    page = None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="parser-agent-generic-browser/1.0",
                viewport={"width": 1366, "height": 900},
            )
            response = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                logger.info("Browser fallback networkidle timeout ignored: url=%s", url)
            html_text = await page.content()
            status = response.status if response is not None else 200
            return status, html_text
    except PlaywrightTimeoutError as exc:
        logger.warning("Browser fallback timeout: url=%s", url)
        raise ScrapingError("Browser fallback timed out.") from exc
    except PlaywrightError as exc:
        logger.warning("Browser fallback failed: url=%s error=%s", url, exc)
        raise ScrapingError(f"Browser fallback failed: {exc}") from exc
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                logger.debug("Browser fallback page close failed", exc_info=True)
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.debug("Browser fallback browser close failed", exc_info=True)


async def _fetch_html_with_session(session: aiohttp.ClientSession, url: str) -> tuple[int, str]:
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            return response.status, await response.text(errors="replace")
    except aiohttp.ClientError as exc:
        logger.warning("Generic scraper network error: url=%s error=%s", url, exc)
        raise ScrapingError(f"Could not fetch page: {exc}") from exc
    except TimeoutError as exc:
        logger.warning("Generic scraper timeout: url=%s", url)
        raise ScrapingError("Page fetch timed out.") from exc


async def fetch_page_sequence(
    start_url: str,
    *,
    follow_pagination: bool = False,
    delay_seconds: float = 0.0,
    max_pages: int = 50,
    fetcher: Callable[[str], Awaitable[tuple[int, str]]] = fetch_html,
) -> list[PageFetch]:
    if max_pages < 1:
        raise ScrapingError("max_pages must be at least 1.")

    pages: list[PageFetch] = []
    seen_urls: set[str] = set()
    next_url: str | None = start_url
    while next_url and next_url not in seen_urls and len(pages) < max_pages:
        seen_urls.add(next_url)
        status, html_text = await fetcher(next_url)
        pages.append(PageFetch(url=next_url, http_status=status, html_text=html_text))
        if not follow_pagination:
            break
        next_url = detect_next_page_url(html_text, next_url)
        if next_url and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    return pages


def detect_next_page_url(html_text: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html_text or "", "lxml")
    selectors = ("li.next a[href]", ".next a[href]", "a[rel='next'][href]")
    for selector in selectors:
        element = soup.select_one(selector)
        if isinstance(element, Tag) and element.get("href"):
            return urljoin(current_url, str(element["href"]))

    for element in soup.select("a[href]"):
        label = element.get_text(" ", strip=True).lower()
        if label in {"next", "next page", ">"}:
            return urljoin(current_url, str(element["href"]))
    return None


def extract_product_records(html_text: str, base_url: str, fields: list[str] | tuple[str, ...] | None = None) -> list[dict[str, str]]:
    selected_fields = normalize_fields(list(fields or DEFAULT_FIELDS))
    soup = BeautifulSoup(html_text or "", "lxml")
    cards = _find_product_cards(soup)
    records = [_record_from_card(card, base_url, selected_fields) for card in cards]
    return [record for record in records if any(record.values())]


def extract_records_adaptive(
    html_text: str,
    base_url: str,
    fields: list[str] | tuple[str, ...] | None = None,
    *,
    focus_terms: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    selected_fields = normalize_fields(list(fields or DEFAULT_FIELDS))
    card_records = extract_product_records(html_text, base_url, selected_fields)
    if card_records:
        return _filter_records_by_focus(card_records, focus_terms)

    parser = UniversalHtmlParser()
    result = parser.parse(base_url, html=html_text)
    if not result.entities:
        return []

    records = [_record_from_entity(entity, selected_fields) for entity in result.entities]
    return _filter_records_by_focus(records, focus_terms)


async def extract_records_from_discovered_pages(
    pages: list[PageFetch],
    fields: list[str] | tuple[str, ...],
    *,
    focus_terms: list[str] | tuple[str, ...] | None = None,
    delay_seconds: float = 0.0,
    max_links: int = DEFAULT_DISCOVERY_LIMIT,
    fetcher: Callable[[str], Awaitable[tuple[int, str]]] = fetch_html,
) -> list[dict[str, str]]:
    links: list[str] = []
    for page in pages:
        links.extend(discover_relevant_links(page.html_text, page.url, focus_terms=focus_terms))
    links = list(dict.fromkeys(links))[:max_links]
    records: list[dict[str, str]] = []
    for index, link in enumerate(links):
        if index and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            _, html_text = await fetcher(link)
        except ScrapingError as exc:
            logger.warning("Generic scraper discovered page fetch failed: url=%s error=%s", link, exc)
            continue
        records.extend(extract_records_adaptive(html_text, link, fields, focus_terms=focus_terms))
    return records


def discover_relevant_links(
    html_text: str,
    base_url: str,
    *,
    focus_terms: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    soup = BeautifulSoup(html_text or "", "lxml")
    base_host = urlparse(base_url).netloc
    terms = _expanded_focus_terms(focus_terms)
    links: list[str] = []

    for anchor in soup.select("a[href]"):
        if not isinstance(anchor, Tag):
            continue
        href = str(anchor.get("href") or "")
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base_host:
            continue
        if _same_document_url(url, base_url):
            continue
        label = " ".join(anchor.get_text(" ", strip=True).split())
        haystack = f"{label} {parsed.path}".lower()
        if terms and not any(term in haystack for term in terms):
            continue
        if not terms and not _looks_like_detail_or_menu_link(haystack):
            continue
        links.append(url)

    return links


async def enrich_records_from_detail_pages(
    records: list[dict[str, str]],
    fields: list[str] | tuple[str, ...],
    *,
    delay_seconds: float = 0.0,
    concurrency: int = 5,
    fetcher: Callable[[str], Awaitable[tuple[int, str]]] = fetch_html,
) -> None:
    selected_fields = normalize_fields(list(fields))
    detail_fields = [field for field in selected_fields if field in DETAIL_FIELDS]
    if not detail_fields:
        return

    semaphore = asyncio.Semaphore(max(1, min(concurrency, 20)))
    shared_session: aiohttp.ClientSession | None = None
    if fetcher is fetch_html:
        timeout = aiohttp.ClientTimeout(total=20.0)
        headers = {
            "User-Agent": "parser-agent-generic-scraper/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        shared_session = aiohttp.ClientSession(timeout=timeout, headers=headers)

    async def enrich_one(index: int, record: dict[str, str]) -> None:
        product_url = record.get("product_url", "")
        if not product_url:
            return
        async with semaphore:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds * (index % max(1, concurrency)))
            try:
                if shared_session is not None:
                    _, html_text = await _fetch_html_with_session(shared_session, product_url)
                else:
                    _, html_text = await fetcher(product_url)
            except ScrapingError as exc:
                logger.warning("Generic scraper detail fetch failed: url=%s error=%s", product_url, exc)
                return
            details = extract_product_detail_fields(html_text)
            for field in detail_fields:
                value = details.get(field, "")
                if value:
                    record[field] = value

    try:
        await asyncio.gather(*(enrich_one(index, record) for index, record in enumerate(records)))
    finally:
        if shared_session is not None:
            await shared_session.close()


def extract_product_detail_fields(html_text: str) -> dict[str, str]:
    soup = BeautifulSoup(html_text or "", "lxml")
    product_info = _extract_product_info_table(soup)
    details = {
        "upc": product_info.get("upc", ""),
        "product_type": product_info.get("product_type", ""),
        "tax": product_info.get("tax", ""),
        "number_of_reviews": product_info.get("number_of_reviews", ""),
        "description": _extract_detail_description(soup),
        "availability": product_info.get("availability", ""),
        "price": product_info.get("price_excl_tax") or product_info.get("price_incl_tax", ""),
        "rating": _extract_rating(soup),
    }
    return details


def _extract_product_info_table(soup: BeautifulSoup) -> dict[str, str]:
    key_map = {
        "upc": "upc",
        "product type": "product_type",
        "price (excl. tax)": "price_excl_tax",
        "price (incl. tax)": "price_incl_tax",
        "tax": "tax",
        "availability": "availability",
        "number of reviews": "number_of_reviews",
    }
    values: dict[str, str] = {}
    for row in soup.select("table tr"):
        if not isinstance(row, Tag):
            continue
        header = row.select_one("th")
        value = row.select_one("td")
        if not header or not value:
            continue
        key = re.sub(r"\s+", " ", header.get_text(" ", strip=True)).lower()
        mapped = key_map.get(key)
        if mapped:
            values[mapped] = " ".join(value.get_text(" ", strip=True).split())
    return values


def _extract_detail_description(soup: BeautifulSoup) -> str:
    heading = soup.select_one("#product_description")
    if heading:
        sibling = heading.find_next_sibling("p")
        if sibling:
            return " ".join(sibling.get_text(" ", strip=True).split())
    for selector in ("[itemprop='description']", ".product_page p"):
        element = soup.select_one(selector)
        if element:
            return " ".join(element.get_text(" ", strip=True).split())
    return ""


def validate_records(records: list[dict[str, str]], fields: list[str] | tuple[str, ...]) -> ValidationReport:
    warnings: list[str] = []
    if not records:
        warnings.append("No product records were extracted.")

    for field_name in fields:
        if any(record.get(field_name) for record in records):
            continue
        warnings.append(f"Field '{field_name}' is empty for all records.")

    seen_urls: set[str] = set()
    duplicate_urls = 0
    for record in records:
        product_url = record.get("product_url", "")
        if not product_url:
            continue
        if product_url in seen_urls:
            duplicate_urls += 1
        seen_urls.add(product_url)
    if duplicate_urls:
        warnings.append(f"Duplicate product_url values: {duplicate_urls}.")

    return ValidationReport(ok=not warnings, warnings=warnings)


def export_csv(records: list[dict[str, str]], fields: list[str] | tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8-sig")


def build_csv_filename(url: str) -> str:
    host = re.sub(r"[^a-z0-9]+", "_", (urlparse(url).netloc or "scrape").lower()).strip("_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"scrape_{host or 'site'}_{stamp}.csv"


def _delay_seconds_for(task: StructuredTask) -> float:
    raw = task.parameters.get("delay_seconds")
    if raw is not None:
        try:
            return max(0.0, min(float(raw), 10.0))
        except (TypeError, ValueError):
            return 1.0
    if "delay" in task.requirements:
        return 1.0
    return 0.0


def _find_product_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = [
        "article.product_pod",
        "[itemtype*='Product']",
        "[data-product-id]",
        ".product",
        ".product-card",
        ".catalog-item",
        ".card",
    ]
    for selector in selectors:
        cards = [tag for tag in soup.select(selector) if isinstance(tag, Tag)]
        if cards:
            return cards
    return []


def _record_from_entity(entity, fields: list[str]) -> dict[str, str]:
    full = {
        "title": entity.title,
        "price": _format_price(entity.price),
        "availability": "",
        "rating": "",
        "product_url": entity.url,
        "image_url": "",
        "description": entity.description,
        "upc": "",
        "product_type": "",
        "tax": "",
        "number_of_reviews": "",
        "entity_type": entity.entity_type,
        "source": entity.source,
    }
    return {field: full.get(field, "") for field in fields}


def _format_price(price: float | int | None) -> str:
    if price is None:
        return ""
    if float(price).is_integer():
        return str(int(price))
    return str(price)


def _focus_terms_for(task: StructuredTask) -> list[str]:
    raw = task.parameters.get("focus_terms")
    if isinstance(raw, list):
        return [str(item).lower() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [item.strip().lower() for item in raw.split(",") if item.strip()]
    return []


def _filter_records_by_focus(
    records: list[dict[str, str]],
    focus_terms: list[str] | tuple[str, ...] | None,
) -> list[dict[str, str]]:
    terms = _expanded_focus_terms(focus_terms)
    if not terms:
        return records
    filtered = []
    for record in records:
        haystack = " ".join(str(value) for value in record.values()).lower()
        if any(term in haystack for term in terms):
            filtered.append(record)
    return filtered


def _expanded_focus_terms(focus_terms: list[str] | tuple[str, ...] | None) -> list[str]:
    terms = [str(term).lower().strip() for term in (focus_terms or []) if str(term).strip()]
    if any(term.startswith("мяс") for term in terms):
        terms.extend(["мяс", "свини", "говяд", "баранин", "куриц", "стейк", "ребр", "крыл", "кебаб", "люля"])
    if any(term.startswith("шаш") for term in terms):
        terms.extend(["шаш", "шампур", "мангал"])
    return list(dict.fromkeys(terms))


def _same_document_url(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    return parsed.scheme == base.scheme and parsed.netloc == base.netloc and parsed.path == base.path


def _looks_like_detail_or_menu_link(haystack: str) -> bool:
    markers = (
        "menu",
        "catalog",
        "restaurant",
        "restoran",
        "product",
        "item",
        "меню",
        "ресторан",
        "каталог",
        "товар",
        "блюд",
    )
    return any(marker in haystack for marker in markers)


def _record_from_card(card: Tag, base_url: str, fields: list[str]) -> dict[str, str]:
    full = {
        "title": _extract_title(card),
        "price": _extract_price(card),
        "availability": _extract_availability(card),
        "rating": _extract_rating(card),
        "product_url": _extract_product_url(card, base_url),
        "image_url": _extract_image_url(card, base_url),
        "description": _extract_description(card),
        "upc": "",
        "product_type": "",
        "tax": "",
        "number_of_reviews": "",
    }
    return {field: full.get(field, "") for field in fields}


def _extract_title(card: Tag) -> str:
    for selector in ("h3 a[title]", "a[title]", "[itemprop='name']", "h3 a", "h2 a", ".title", ".name"):
        element = card.select_one(selector)
        if not element:
            continue
        title = element.get("title") if isinstance(element, Tag) else ""
        value = title or element.get_text(" ", strip=True)
        if value:
            return str(value).strip()
    return ""


def _extract_price(card: Tag) -> str:
    for selector in (".price_color", "[itemprop='price']", ".price", ".product-price"):
        element = card.select_one(selector)
        if element:
            value = element.get("content") if isinstance(element, Tag) else ""
            return str(value or element.get_text(" ", strip=True)).strip()
    text = card.get_text(" ", strip=True)
    match = re.search(r"(?:[$€£]|руб\.?|₽)\s*[\d\s.,]+|[\d\s.,]+\s*(?:[$€£]|руб\.?|₽)", text, flags=re.I)
    return match.group(0).strip() if match else ""


def _extract_availability(card: Tag) -> str:
    for selector in (".availability", "[itemprop='availability']", ".stock", ".status"):
        element = card.select_one(selector)
        if element:
            return " ".join(element.get_text(" ", strip=True).split())
    return ""


def _extract_rating(card: Tag) -> str:
    for selector in (".star-rating", "[class*='rating']", "[aria-label*='rating' i]"):
        element = card.select_one(selector)
        if not isinstance(element, Tag):
            continue
        aria = element.get("aria-label")
        if aria:
            return str(aria).strip()
        for class_name in element.get("class", []):
            if class_name in RATING_WORDS:
                return class_name
        text = element.get_text(" ", strip=True)
        if text:
            return text
    return ""


def _extract_product_url(card: Tag, base_url: str) -> str:
    for selector in ("h3 a[href]", "a[href]", "[itemprop='url']"):
        element = card.select_one(selector)
        if isinstance(element, Tag) and element.get("href"):
            return urljoin(base_url, str(element["href"]))
    return ""


def _extract_image_url(card: Tag, base_url: str) -> str:
    element = card.select_one("img[src]")
    if isinstance(element, Tag) and element.get("src"):
        return urljoin(base_url, str(element["src"]))
    return ""


def _extract_description(card: Tag) -> str:
    for selector in ("[itemprop='description']", ".description", ".product-description"):
        element = card.select_one(selector)
        if element:
            return " ".join(element.get_text(" ", strip=True).split())
    return ""
