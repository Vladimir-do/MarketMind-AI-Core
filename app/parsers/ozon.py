# @skills: parser-base-contract, parser-marketplace-router, playwright-ozon-stealth-fetch
"""
ozon.py — парсер Озон через Playwright (ninja-режим).
"""
import aiohttp
import asyncio
import json
import random
from time import perf_counter
from urllib.parse import quote, urlparse

from app.config import logger, DELAY_MIN, DELAY_MAX, RETRY_ATTEMPTS, PROXY
from app.parsers.base import BaseParser, ProductData
from app.updater import (
    USER_AGENTS,
    VIEWPORTS,
    STEALTH_SCRIPT,
    _image_from_img_tag,
    parse_ozon_api_json,
    parse_ozon_html,
    _is_ozon_blocked_text,
)
from app.utils.error_research import research_parse_failure


OZON_API_URLS = [
    "https://www.ozon.ru/api/composer-api.bx/page/json/v2?url={encoded}",
    "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={encoded}",
]


def _ozon_api_urls(url: str) -> list[str]:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    encoded = quote(path, safe="")
    return [api.format(encoded=encoded) for api in OZON_API_URLS]


class OzonParser(BaseParser):
    """Парсер Озона с ninja anti-detection."""

    def __init__(self):
        self._pw = None
        self._browser = None

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "ozon.ru" in url

    async def start(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--lang=ru-RU",
            ],
        }
        if PROXY:
            launch_args["proxy"] = {"server": PROXY}
        self._browser = await self._pw.chromium.launch(**launch_args)

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _fetch_api_data(self, url: str) -> dict | None:
        request_proxy = PROXY if PROXY else None
        if request_proxy and request_proxy.startswith(("socks5://", "socks4://", "socks5h://")):
            request_proxy = None

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.ozon.ru/",
            "Origin": "https://www.ozon.ru",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for api_url in _ozon_api_urls(url):
                t0 = perf_counter()
                try:
                    async with session.get(
                        api_url,
                        timeout=aiohttp.ClientTimeout(total=15),
                        proxy=request_proxy,
                    ) as resp:
                        latency_ms = int((perf_counter() - t0) * 1000)
                        if resp.status != 200:
                            logger.debug(f"Ozon API {api_url}: status {resp.status}")
                            continue

                        text = await resp.text()
                        if _is_ozon_blocked_text(text):
                            logger.warning(f"Ozon API blocked response detected: {api_url}")
                            continue

                        try:
                            payload = await resp.json(content_type=None)
                        except Exception:
                            try:
                                payload = json.loads(text or "{}")
                            except Exception:
                                continue

                        data = parse_ozon_api_json(payload, url)
                        if data:
                            return data
                except Exception as exc:
                    logger.debug(f"Ozon API fetch error for {api_url}: {exc}")
                    continue
        return None

    async def _fetch_html(self, url: str) -> str | None:
        ctx = await self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
        )
        await ctx.add_init_script(STEALTH_SCRIPT)
        page = await ctx.new_page()
        try:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    if attempt == 0:
                        await page.goto("https://www.ozon.ru/", wait_until="domcontentloaded", timeout=20_000)
                        await asyncio.sleep(random.uniform(2, 3))
                    await page.goto(url, wait_until="load", timeout=60_000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=30_000)
                    except Exception:
                        pass
                    await page.wait_for_selector("h1", timeout=12_000)
                    await asyncio.sleep(random.uniform(2, 3))
                    # Скролл
                    for _ in range(random.randint(5, 7)):
                        await page.mouse.wheel(0, random.randint(600, 900))
                        await asyncio.sleep(random.uniform(0.6, 1.0))
                    for _ in range(2):
                        await page.mouse.wheel(0, -random.randint(400, 700))
                        await asyncio.sleep(random.uniform(0.4, 0.8))
                    try:
                        await page.wait_for_function(
                            """() => Array.from(document.images)
                                .some((img) => img.complete && img.naturalWidth > 0)""",
                            timeout=10_000,
                        )
                    except Exception:
                        logger.debug("Ozon images did not finish loading before HTML capture")
                    html = await page.content()
                    if "доступ ограничен" in html.lower():
                        await asyncio.sleep(random.uniform(10, 20))
                        continue
                    return html
                except Exception as e:
                    logger.warning(f"Ozon попытка {attempt+1}: {e}")
                    await asyncio.sleep(random.uniform(5, 10))
            return None
        finally:
            await ctx.close()

    async def fetch_product(self, url: str) -> ProductData | None:
        api_data = await self._fetch_api_data(url)
        if api_data:
            return ProductData(
                name=api_data["name"],
                price=api_data["price"],
                old_price=None,
                discount_pct=None,
                availability=api_data["availability"],
                url=url,
                image_url=api_data.get("image_url"),
                marketplace="ozon",
            )

        html = await self._fetch_html(url)
        if not html:
            try:
                await research_parse_failure(
                    source="ozon_parser_no_html",
                    url=url,
                    detail="OzonParser: _fetch_html вернул None",
                    marketplace="ozon",
                )
            except Exception:
                pass
            return None
        data = parse_ozon_html(html, url)
        if not data:
            try:
                await research_parse_failure(
                    source="ozon_parser_parse_failed",
                    url=url,
                    detail="OzonParser: parse_ozon_html вернул None",
                    marketplace="ozon",
                )
            except Exception:
                pass
        return ProductData(
            name=data["name"],
            price=data["price"],
            old_price=None,
            discount_pct=None,
            availability=data["availability"],
            url=url,
            image_url=data.get("image_url"),
            marketplace="ozon",
        )

    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        from app.searcher import search_ozon
        raw = await search_ozon(query, max_results)
        return [
            ProductData(
                name=r["name"], price=r["price"], old_price=None, discount_pct=None,
                availability="in_stock", url=r["url"], image_url=r.get("image_url"),
                marketplace="ozon",
            )
            for r in raw
        ]
