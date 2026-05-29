"""
searcher.py — поиск товаров на Озоне по названию через Playwright.
Возвращает список найденных товаров с ценами.
"""
import asyncio
import os
import re
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.config import logger, DELAY_MIN, DELAY_MAX
from app.updater import USER_AGENTS, VIEWPORTS, STEALTH_SCRIPT, _is_ozon_blocked_text
import random

_ozon_search_blocked_until = 0.0
_ozon_search_block_reason = ""


def ozon_search_blocked_message() -> str | None:
    remaining = int(_ozon_search_blocked_until - time.monotonic())
    if remaining <= 0:
        return None
    minutes = max(1, remaining // 60)
    reason = f": {_ozon_search_block_reason}" if _ozon_search_block_reason else ""
    return f"Поиск Ozon временно недоступен{reason}. Повторите примерно через {minutes} мин."


def _mark_ozon_search_blocked(reason: str) -> None:
    global _ozon_search_blocked_until, _ozon_search_block_reason
    cooldown_minutes = int(os.getenv("OZON_SEARCH_BLOCK_COOLDOWN_MINUTES", "20") or "20")
    cooldown_minutes = max(1, min(cooldown_minutes, 180))
    _ozon_search_blocked_until = time.monotonic() + cooldown_minutes * 60
    _ozon_search_block_reason = reason[:120]
    logger.warning(f"Ozon search paused for {cooldown_minutes} min: {_ozon_search_block_reason}")


def _reset_ozon_search_block_state() -> None:
    global _ozon_search_blocked_until, _ozon_search_block_reason
    _ozon_search_blocked_until = 0.0
    _ozon_search_block_reason = ""


async def search_ozon(query: str, max_results: int = 5) -> list[dict]:
    """
    Ищет товары на Озоне по запросу.
    Возвращает список словарей: name, price, url, image_url
    """
    from playwright.async_api import async_playwright

    blocked_message = ozon_search_blocked_message()
    if blocked_message:
        logger.info(f"Поиск Ozon пропущен для '{query}': {blocked_message}")
        return []

    search_url = f"https://www.ozon.ru/search/?text={quote_plus(query)}&from_global=true"
    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
        )
        await ctx.add_init_script(STEALTH_SCRIPT)
        page = await ctx.new_page()

        try:
            # Сначала главная
            await page.goto("https://www.ozon.ru/", wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(random.uniform(2, 3))

            # Поисковая страница
            await page.goto(search_url, wait_until="load", timeout=60_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            try:
                await page.wait_for_selector("div[data-widget='searchResultsV2']", timeout=12_000)
            except Exception:
                logger.warning("Результаты поиска не появились")

            await asyncio.sleep(random.uniform(2, 3))

            # Скролл
            for _ in range(5):
                await page.mouse.wheel(0, random.randint(600, 900))
                await asyncio.sleep(random.uniform(0.6, 1.0))
            try:
                await page.wait_for_function(
                    """() => Array.from(document.images)
                        .some((img) => img.complete && img.naturalWidth > 0)""",
                    timeout=10_000,
                )
            except Exception:
                logger.debug("Search result images did not finish loading before HTML capture")

            html = await page.content()
            if _is_ozon_blocked_text(html):
                _mark_ozon_search_blocked("abt-challenge/antibot")
                return []

            results = _parse_search_results(html, max_results)
            logger.info(f"Найдено товаров по запросу '{query}': {len(results)}")

        except Exception as e:
            logger.error(f"Ошибка поиска '{query}': {e}")
        finally:
            await ctx.close()
            await browser.close()

    return results


def _parse_search_results(html: str, max_results: int) -> list[dict]:
    """Парсит HTML страницы поиска Озон."""
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Карточки товаров в поиске
    cards = soup.select("div[data-widget='searchResultsV2'] > div > div")
    if not cards:
        # Альтернативный селектор
        cards = soup.select("div.widget-search-result-container div[class*='tile']")

    for card in cards:
        if len(results) >= max_results:
            break
        try:
            # Ссылка и название
            link = card.select_one("a[href*='/product/']")
            if not link:
                continue
            href = link.get("href", "")
            url = f"https://www.ozon.ru{href}" if href.startswith("/") else href

            name_elem = card.select_one("span[class*='tile-hover-target'], a span")
            name = name_elem.get_text(strip=True) if name_elem else link.get_text(strip=True)
            if not name or len(name) < 3:
                continue

            # Цена
            price = None
            for sel in ["span[class*='price']", "div[class*='price']", "span[class*='Price']"]:
                for elem in card.select(sel):
                    txt = re.sub(r"[^\d]", "", elem.get_text(strip=True))
                    if txt and 10 < int(txt) < 10_000_000:
                        price = int(txt)
                        break
                if price:
                    break

            # Изображение
            img = card.select_one("img")
            image_url = None
            if img:
                src = img.get("src") or img.get("data-src", "")
                if src and src.startswith("http"):
                    image_url = src

            if url and name:
                results.append({
                    "name": name[:100],
                    "price": price,
                    "url": url,
                    "image_url": image_url,
                })
        except Exception:
            continue

    return results
