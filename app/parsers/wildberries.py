"""
wildberries.py — парсер Wildberries через API.
Поддерживает несколько версий API с автофоллбэком.
"""
import json
import re
from time import perf_counter
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import aiohttp
try:
    from aiohttp_socks import ProxyConnector  # type: ignore
except Exception:  # pragma: no cover
    ProxyConnector = None

from app.config import (
    WB_CLOUD_FALLBACK_LOCAL,
    WB_CLOUD_FIRST,
    WB_CLOUD_FUNCTION_URL,
    logger,
)
from app.parsers.base import BaseParser, ProductData
from app.utils.error_research import research_parse_failure
from app.utils.proxy import proxy_is_reachable


def _extract_wb_id(url: str) -> int | None:
    """Извлекает числовой ID товара из URL Wildberries."""
    raw = (url or "").strip()
    if re.fullmatch(r"\d{6,12}", raw):
        return int(raw)

    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    for key in ("nm", "nm_id", "nmId"):
        value = query.get(key, [None])[0]
        if value and re.fullmatch(r"\d{6,12}", value):
            return int(value)

    match = re.search(r"(?:^|/)catalog/(\d{6,12})(?:/|$)", parsed.path)
    if match:
        return int(match.group(1))
    return None


WB_BASKET_RANGES = [
    (143, "01"),
    (287, "02"),
    (431, "03"),
    (719, "04"),
    (1007, "05"),
    (1061, "06"),
    (1115, "07"),
    (1169, "08"),
    (1313, "09"),
    (1601, "10"),
    (1655, "11"),
    (1919, "12"),
    (2045, "13"),
    (2189, "14"),
    (2405, "15"),
    (2621, "16"),
    (2837, "17"),
    (3059, "18"),
    (3273, "19"),
    (3487, "20"),
    (3731, "21"),
    (3975, "22"),
    (4219, "23"),
    (4455, "24"),
    (4699, "25"),
    (4943, "26"),
    (5187, "27"),
    (5431, "28"),
    (5675, "29"),
    (5919, "30"),
    (6163, "31"),
    (6407, "32"),
    (6651, "33"),
    (6895, "34"),
    (7139, "35"),
    (7383, "36"),
    (7627, "37"),
    (7871, "38"),
    (8115, "39"),
    (8359, "40"),
]


def _get_basket_host(nm_id: int) -> str:
    vol = nm_id // 100000
    for max_vol, basket in WB_BASKET_RANGES:
        if vol <= max_vol:
            return f"https://basket-{basket}.wb.ru"
    return "https://basket-41.wb.ru"


def _wbbasket_candidates(nm_id: int) -> list[str]:
    primary = _get_basket_host(nm_id).split("basket-", 1)[1].split(".", 1)[0]
    fallback = [f"{i:02d}" for i in range(1, 81)]
    return [primary] + [b for b in fallback if b != primary]


def _wb_path_parts(nm_id: int) -> tuple[int, int]:
    return nm_id // 100000, nm_id // 1000


def _build_wb_image_url(nm_id: int, basket: str | None = None) -> str:
    vol, part = _wb_path_parts(nm_id)
    host = f"https://basket-{basket}.wb.ru" if basket else _get_basket_host(nm_id)
    return f"{host}/vol{vol}/part{part}/{nm_id}/images/big/1.webp"


def _build_wb_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.wildberries.ru",
        "Referer": "https://www.wildberries.ru/",
        "Sec-Ch-Ua": "\"Chromium\";v=\"122\", \"Not(A:Brand\";v=\"24\", \"Google Chrome\";v=\"122\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

# Несколько версий API — пробуем по очереди
API_URLS = [
    "https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}",
    "https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}",
    "https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}",
]
WB_WARMUP_SEARCH_URL = (
    "https://search.wb.ru/exactmatch/ru/common/v4/search"
    "?appType=1&curr=rub&dest=-1257786&query=test&resultset=catalog&sort=popular"
)

AttemptRecorder = Callable[..., Awaitable[None]]


class WildberriesParser(BaseParser):
    def __init__(self, attempt_recorder: AttemptRecorder | None = None):
        self._attempt_recorder = attempt_recorder
        self._current_proxy = None

    async def _record_attempt(
        self,
        *,
        url: str,
        source: str,
        status: str,
        latency_ms: int,
        http_status: int | None = None,
        error: Exception | None = None,
    ) -> None:
        if not self._attempt_recorder:
            return
        try:
            await self._attempt_recorder(
                url=url,
                marketplace="wildberries",
                source=source,
                status=status,
                latency_ms=latency_ms,
                http_status=http_status,
                proxy=self._current_proxy,
                error_class=type(error).__name__ if error else None,
                error_text=str(error) if error else None,
            )
        except Exception:
            pass

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "wildberries.ru" in url or "wb.ru" in url

    async def fetch_product(self, url: str, proxy: str | None = None) -> ProductData | None:
        self._current_proxy = proxy
        nm_id = _extract_wb_id(url)
        if not nm_id:
            logger.error(f"WB URL parse error: не удалось извлечь числовой nm_id из URL: {url}")
            try:
                await research_parse_failure(
                    source="wildberries_invalid_url",
                    url=url,
                    detail="Не удалось извлечь nm_id из URL",
                    marketplace="wildberries",
                )
            except Exception:
                pass
            return None

        if WB_CLOUD_FUNCTION_URL and WB_CLOUD_FIRST:
            data = await self._fetch_via_cloud_function(url, nm_id)
            if data:
                return data
            if not WB_CLOUD_FALLBACK_LOCAL:
                return None
            logger.warning("WB cloud fetch failed, falling back to local WB sources")

        logger.info(f"WB: парсим товар ID={nm_id}")
        failure_reasons: list[str] = []

        if proxy and not proxy_is_reachable(proxy):
            logger.warning(f"WB: прокси недоступен (не слушает порт): {proxy}. Пробую без прокси.")
            proxy = None
        self._current_proxy = proxy

        connector = None
        request_proxy = proxy
        if proxy and proxy.startswith(("socks5://", "socks4://", "socks5h://")):
            if ProxyConnector is None:
                logger.warning(
                    "WB: задан SOCKS-прокси, но пакет aiohttp-socks не установлен. "
                    "Установите: pip install aiohttp-socks"
                )
                request_proxy = None
            else:
                connector = ProxyConnector.from_url(proxy)
                request_proxy = None  # для socks-прокси proxy=... не нужен

        async with aiohttp.ClientSession(headers=_build_wb_headers(), connector=connector) as session:
            await self._warmup_wb_session(session, proxy=request_proxy)

            # Пробуем все версии API
            for api_template in API_URLS:
                api_url = api_template.format(nm_id=nm_id)
                t0 = perf_counter()
                try:
                    async with session.get(
                        api_url,
                        timeout=aiohttp.ClientTimeout(total=20),
                        proxy=request_proxy,
                    ) as resp:
                        latency_ms = int((perf_counter() - t0) * 1000)
                        if resp.status != 200:
                            reason = f"api http {resp.status}: {api_url}"
                            failure_reasons.append(reason)
                            logger.warning(f"WB server response error: {reason}")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="blocked" if resp.status in {403, 429} else "http_error",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                            )
                            continue

                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            failure_reasons.append(f"api invalid json body: {api_url}")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="parse_error",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                            )
                            continue

                        products = data.get("data", {}).get("products", [])
                        if not products:
                            reason = f"api not_found: {api_url}"
                            failure_reasons.append(reason)
                            logger.warning(f"WB server response: товар {nm_id} не найден в API ({api_url})")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="not_found",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                            )
                            continue

                        await self._record_attempt(
                            url=url,
                            source="api",
                            status="ok",
                            http_status=resp.status,
                            latency_ms=latency_ms,
                        )
                        return self._parse_product(products[0], url, nm_id, session)

                except Exception as e:
                    failure_reasons.append(f"api exception {type(e).__name__}: {e}")
                    logger.warning(f"WB API {api_url} exception: {type(e).__name__}: {e}")
                    await self._record_attempt(
                        url=url,
                        source="api",
                        status="error",
                        latency_ms=int((perf_counter() - t0) * 1000),
                        error=e,
                    )
                    continue

            # Если API не сработал — пробуем через страницу поиска
            logger.info(f"WB: API не сработал, пробуем поиск по ID {nm_id}")
            data = await self._fetch_via_search(session, nm_id, url, proxy=proxy)
            if data:
                # На WB поисковый API иногда возвращает карточку без цен.
                # В этом случае пробуем wbbasket card.json.
                if data.price is not None or data.old_price is not None:
                    return data

            # Последний шанс: wbbasket card.json (часто работает когда card.wb.ru 403)
            data = await self._fetch_via_wbbasket_card_json(session, nm_id, url, proxy=proxy)
            if not data:
                summary = "; ".join(failure_reasons[-6:]) or "нет успешного ответа от API/search/wbbasket"
                logger.error(
                    f"WB fetch failed for nm_id={nm_id}: {summary}. "
                    "Это не ошибка парсинга URL, артикул извлечен корректно."
                )
                try:
                    await research_parse_failure(
                        source="wildberries_all_sources_empty",
                        url=url,
                        detail=f"nm_id={nm_id}: card API, поиск и wbbasket не вернули карточку; {summary}",
                        marketplace="wildberries",
                    )
                except Exception:
                    pass
            return data

    async def _fetch_via_cloud_function(self, url: str, nm_id: int) -> ProductData | None:
        t0 = perf_counter()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    WB_CLOUD_FUNCTION_URL,
                    json={"product_id": nm_id},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    latency_ms = int((perf_counter() - t0) * 1000)
                    if resp.status != 200:
                        await self._record_attempt(
                            url=url,
                            source="cloud_function",
                            status="blocked" if resp.status in {403, 429} else "http_error",
                            http_status=resp.status,
                            latency_ms=latency_ms,
                        )
                        return None

                    payload = await resp.json(content_type=None)
                    data = self._parse_cloud_payload(payload, url, nm_id)
                    await self._record_attempt(
                        url=url,
                        source="cloud_function",
                        status="ok" if data else "parse_error",
                        http_status=resp.status,
                        latency_ms=latency_ms,
                    )
                    return data
        except Exception as e:
            await self._record_attempt(
                url=url,
                source="cloud_function",
                status="error",
                latency_ms=int((perf_counter() - t0) * 1000),
                error=e,
            )
            logger.warning(f"WB cloud function error for {nm_id}: {type(e).__name__}: {e}")
            return None

    def _parse_cloud_payload(self, payload: dict, url: str, nm_id: int) -> ProductData | None:
        if payload.get("name") and "price" in payload:
            return ProductData(
                name=payload.get("name") or f"Wildberries #{nm_id}",
                price=payload.get("price"),
                old_price=payload.get("old_price"),
                discount_pct=payload.get("discount_pct"),
                availability=payload.get("availability", "out_of_stock"),
                url=url,
                image_url=payload.get("image_url"),
                rating=payload.get("rating"),
                reviews_count=payload.get("reviews_count"),
                seller_name=payload.get("seller_name"),
                brand=payload.get("brand"),
                marketplace="wildberries",
            )

        products = payload.get("data", {}).get("products") or payload.get("products") or []
        if not products:
            return None
        return self._parse_product(products[0], url, nm_id, None)

    def _parse_product(self, p: dict, url: str, nm_id: int, session) -> ProductData:
        sizes = p.get("sizes", [])

        price = None
        old_price = None
        for size in sizes:
            price_data = size.get("price", {})
            if price_data.get("product"):
                price = price_data["product"] // 100
                old_price_raw = price_data.get("basic", 0)
                if old_price_raw and old_price_raw != price_data["product"]:
                    old_price = old_price_raw // 100
                break

        discount_pct = None
        if price and old_price and old_price > price:
            discount_pct = round((old_price - price) / old_price * 100)

        in_stock = any(
            stock.get("qty", 0) > 0
            for size in sizes
            for stock in size.get("stocks", [])
        )
        availability = "in_stock" if in_stock else "out_of_stock"

        image_url = _build_wb_image_url(nm_id)

        name = p.get("name", "")
        brand = p.get("brand", "")
        if brand and brand.lower() not in name.lower():
            name = f"{brand} {name}".strip()

        return ProductData(
            name=name,
            price=price,
            old_price=old_price,
            discount_pct=discount_pct,
            availability=availability,
            url=url,
            image_url=image_url,
            rating=p.get("reviewRating"),
            reviews_count=p.get("feedbacks"),
            seller_name=p.get("brand"),
            brand=p.get("brand"),
            marketplace="wildberries",
        )

    async def _fetch_via_search(
        self,
        session: aiohttp.ClientSession,
        nm_id: int,
        url: str,
        proxy: str | None = None,
    ) -> ProductData | None:
        """Запасной вариант — ищем товар через поисковый API WB."""
        try:
            search_url = f"https://search.wb.ru/exactmatch/ru/common/v5/search?appType=1&curr=rub&dest=-1257786&query={nm_id}&resultset=catalog&sort=popular"
            request_proxy = proxy
            if proxy and proxy.startswith(("socks5://", "socks4://", "socks5h://")):
                request_proxy = None

            t0 = perf_counter()
            async with session.get(
                search_url,
                timeout=aiohttp.ClientTimeout(total=15),
                proxy=request_proxy,
            ) as resp:
                latency_ms = int((perf_counter() - t0) * 1000)
                if resp.status != 200:
                    await self._record_attempt(
                        url=url,
                        source="search",
                        status="blocked" if resp.status in {403, 429} else "http_error",
                        http_status=resp.status,
                        latency_ms=latency_ms,
                    )
                    return None
                data = await resp.json(content_type=None)
                products = data.get("data", {}).get("products", [])
                if not products:
                    await self._record_attempt(
                        url=url,
                        source="search",
                        status="not_found",
                        http_status=resp.status,
                        latency_ms=latency_ms,
                    )
                    return None
                await self._record_attempt(
                    url=url,
                    source="search",
                    status="ok",
                    http_status=resp.status,
                    latency_ms=latency_ms,
                )
                # Ищем точное совпадение по ID
                for p in products:
                    if str(p.get("id")) == str(nm_id):
                        return self._parse_product(p, url, nm_id, session)
                # Берём первый если точного совпадения нет
                return self._parse_product(products[0], url, nm_id, session)
        except Exception as e:
            logger.error(f"WB поиск по ID {nm_id} ошибка: {e}")
            await self._record_attempt(
                url=url,
                source="search",
                status="error",
                latency_ms=int((perf_counter() - t0) * 1000) if "t0" in locals() else 0,
                error=e,
            )
            return None

    async def _warmup_wb_session(self, session: aiohttp.ClientSession, proxy: str | None = None) -> None:
        """
        Two-step warmup before card.wb.ru:
        1) Open main WB site to get first-party cookies.
        2) Hit WB search feed endpoint to enrich cookie/session context.
        """
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with session.get(
                "https://www.wildberries.ru/",
                timeout=timeout,
                proxy=proxy,
            ):
                pass
        except Exception:
            pass

        try:
            async with session.get(
                WB_WARMUP_SEARCH_URL,
                timeout=timeout,
                proxy=proxy,
            ):
                pass
        except Exception:
            pass

    async def _fetch_via_wbbasket_card_json(
        self,
        session: aiohttp.ClientSession,
        nm_id: int,
        url: str,
        proxy: str | None = None,
    ) -> ProductData | None:
        """
        Альтернативный источник: wbbasket `card.json`.
        Часто доступен даже когда `card.wb.ru` отвечает 403.
        """
        vol, part = _wb_path_parts(nm_id)
        # Практичный набор — на реальных проектах хватает, чтобы “попасть”
        # (WB периодически добавляет новые корзины).
        candidates = _wbbasket_candidates(nm_id)

        for b in candidates:
            card_url = f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"
            t0 = perf_counter()
            try:
                request_proxy = proxy
                if proxy and proxy.startswith(("socks5://", "socks4://", "socks5h://")):
                    request_proxy = None
                async with session.get(
                    card_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    proxy=request_proxy,
                ) as resp:
                    latency_ms = int((perf_counter() - t0) * 1000)
                    if resp.status != 200:
                        if resp.status != 404:
                            logger.warning(f"WB wbbasket {card_url}: status {resp.status}")
                        await self._record_attempt(
                            url=url,
                            source="wbbasket",
                            status="not_found" if resp.status == 404 else "http_error",
                            http_status=resp.status,
                            latency_ms=latency_ms,
                        )
                        continue
                    data = await resp.json()
            except Exception as e:
                await self._record_attempt(
                    url=url,
                    source="wbbasket",
                    status="error",
                    latency_ms=int((perf_counter() - t0) * 1000),
                    error=e,
                )
                continue

            name = (data.get("imt_name") or "").strip()
            if not name:
                await self._record_attempt(
                    url=url,
                    source="wbbasket",
                    status="parse_error",
                    http_status=200,
                    latency_ms=latency_ms,
                )
                continue

            price = None
            old_price = None
            sizes = data.get("sizes") or []
            if sizes:
                p = (sizes[0].get("price") or {})
                total = p.get("total")
                if isinstance(total, (int, float)):
                    price = int(total) // 100
                basic = p.get("basic")
                if isinstance(basic, (int, float)):
                    old_price = int(basic) // 100
                    if price and old_price == price:
                        old_price = None

            availability = "in_stock" if (data.get("sale") is not None or price is not None) else "out_of_stock"
            discount_pct = None
            if price and old_price and old_price > price:
                discount_pct = round((old_price - price) / old_price * 100)

            image_url = _build_wb_image_url(nm_id, basket=b)

            await self._record_attempt(
                url=url,
                source="wbbasket",
                status="ok",
                http_status=200,
                latency_ms=latency_ms,
            )
            return ProductData(
                name=name,
                price=price,
                old_price=old_price,
                discount_pct=discount_pct,
                availability=availability,
                url=url,
                image_url=image_url,
                rating=None,
                reviews_count=None,
                seller_name=None,
                brand=data.get("selling", {}).get("brand_name") if isinstance(data.get("selling"), dict) else None,
                marketplace="wildberries",
            )

        return None

    async def _fetch_reviews(self, session: aiohttp.ClientSession, nm_id: int) -> list[str]:
        try:
            url = f"https://feedbacks2.wb.ru/feedbacks/v2/{nm_id}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
                feedbacks = data.get("feedbacks", [])
                return [f.get("text", "") for f in feedbacks[:20] if f.get("text")]
        except Exception:
            return []

    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        try:
            import urllib.parse, json
            encoded = urllib.parse.quote(query)
            url = f"https://search.wb.ru/exactmatch/ru/common/v5/search?appType=1&curr=rub&dest=-1257786&query={encoded}&resultset=catalog&sort=popular"
            async with aiohttp.ClientSession(headers=_build_wb_headers()) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return []
                    data = json.loads(await resp.text())

            products = data.get("data", {}).get("products", [])[:max_results]
            results = []
            for p in products:
                nm_id = p.get("id")
                if not nm_id:
                    continue
                sizes = p.get("sizes", [])
                price = None
                old_price = None
                for size in sizes:
                    pd = size.get("price", {})
                    if pd.get("product"):
                        price = pd["product"] // 100
                        basic = pd.get("basic")
                        if isinstance(basic, (int, float)):
                            basic_rub = int(basic) // 100
                            if basic_rub > price:
                                old_price = basic_rub
                        break
                discount_pct = None
                if price and old_price and old_price > price:
                    discount_pct = round((old_price - price) / old_price * 100)
                in_stock = any(
                    stock.get("qty", 0) > 0
                    for size in sizes
                    for stock in size.get("stocks", [])
                )
                results.append(ProductData(
                    name=p.get("name", ""),
                    price=price,
                    old_price=old_price,
                    discount_pct=discount_pct,
                    availability="in_stock" if in_stock else "out_of_stock",
                    url=f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx",
                    image_url=None,
                    rating=p.get("reviewRating"),
                    reviews_count=p.get("feedbacks"),
                    brand=p.get("brand"),
                    marketplace="wildberries",
                ))
            return results
        except Exception as e:
            logger.error(f"WB поиск ошибка: {e}")
            return []
