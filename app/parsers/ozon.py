# @skills: parser-base-contract, parser-marketplace-router, playwright-ozon-stealth-fetch
"""
ozon.py — парсер Озон через Playwright (ninja-режим).
"""

import asyncio
import contextlib
import json
import os
import random
from urllib.parse import quote, urlparse

import aiohttp

from app.config import PROXY, RETRY_ATTEMPTS, logger
from app.parsers.alt_sources import fetch_from_alt_sources
from app.parsers.base import BaseParser, ProductData
from app.parsers.system_proxy import bypass_system_proxy
from app.updater import (
    BROWSER_INIT_SCRIPT,
    USER_AGENTS,
    VIEWPORTS,
    _is_ozon_blocked_text,
    parse_ozon_api_json,
    parse_ozon_html,
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
        self._last_api_blocked = False

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "ozon.ru" in url

    async def start(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
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
        self._last_api_blocked = False
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
            api_statuses = []
            for api_url in _ozon_api_urls(url):
                try:
                    async with session.get(
                        api_url,
                        timeout=aiohttp.ClientTimeout(total=15),
                        proxy=request_proxy,
                    ) as resp:
                        if resp.status != 200:
                            if resp.status in {403, 429}:
                                api_statuses.append(resp.status)
                            logger.debug(f"Ozon API {api_url}: status {resp.status}")
                            continue

                        text = await resp.text()
                        if _is_ozon_blocked_text(text):
                            api_statuses.append("blocked")
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
            if api_statuses and all(status in {403, 429, "blocked"} for status in api_statuses):
                self._last_api_blocked = True
        return None

    async def _fetch_html(self, url: str) -> str | None:
        if not self._browser:
            await self.start()
        async with bypass_system_proxy():
            ctx = await self._browser.new_context(
                viewport=random.choice(VIEWPORTS),
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
            )
            await ctx.add_init_script(BROWSER_INIT_SCRIPT)
            page = await ctx.new_page()
            try:
                for attempt in range(RETRY_ATTEMPTS):
                    try:
                        if attempt == 0:
                            await page.goto("https://www.ozon.ru/", wait_until="domcontentloaded", timeout=20_000)
                            await asyncio.sleep(random.uniform(2, 3))
                        await page.goto(url, wait_until="load", timeout=60_000)
                        with contextlib.suppress(Exception):
                            await page.wait_for_load_state("networkidle", timeout=30_000)
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
                        logger.warning(f"Ozon попытка {attempt + 1}: {e}")
                        base_delay = 5 * (2**attempt)
                        await asyncio.sleep(random.uniform(base_delay, base_delay * 2))
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
                rating=api_data.get("rating"),
                reviews_count=api_data.get("reviews_count"),
                reviews=api_data.get("reviews") or [],
                marketplace="ozon",
            )

        skip_browser_after_api_block = os.getenv(
            "OZON_SKIP_BROWSER_AFTER_API_BLOCK",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if self._last_api_blocked and skip_browser_after_api_block:
            alt_data = await fetch_from_alt_sources(url)
            if alt_data:
                return ProductData(
                    name=alt_data["name"],
                    price=alt_data.get("price"),
                    old_price=None,
                    discount_pct=None,
                    availability=alt_data.get("availability") or "unknown",
                    url=url,
                    image_url=alt_data.get("image_url"),
                    brand=alt_data.get("brand"),
                    marketplace="ozon",
                )
            logger.warning(f"Ozon API blocked; browser fallback skipped: {url}")
            return None

        started_here = not self._browser
        try:
            html = await self._fetch_html(url)
        finally:
            if started_here:
                await self.stop()
        if not html:
            with contextlib.suppress(Exception):
                await research_parse_failure(
                    source="ozon_parser_no_html",
                    url=url,
                    detail="OzonParser: _fetch_html вернул None",
                    marketplace="ozon",
                )
            return None
        data = parse_ozon_html(html, url)
        if not data:
            with contextlib.suppress(Exception):
                await research_parse_failure(
                    source="ozon_parser_parse_failed",
                    url=url,
                    detail="OzonParser: parse_ozon_html вернул None",
                    marketplace="ozon",
                )
            return None
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
                name=r["name"],
                price=r["price"],
                old_price=None,
                discount_pct=None,
                availability="in_stock",
                url=r["url"],
                image_url=r.get("image_url"),
                marketplace="ozon",
            )
            for r in raw
        ]
