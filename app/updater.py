"""
updater.py — 🥷 Ninja-режим парсинга Озон через Playwright.
Максимальная маскировка: случайные UA, имитация человека,
скрытие webdriver, поддержка прокси.
"""
import asyncio
import json
import os
import random
import re
from time import perf_counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.config import logger, DELAY_MIN, DELAY_MAX, RETRY_ATTEMPTS
from app.database import Database, PriceHistory
from app.utils.proxy import proxy_is_reachable
from app.utils.error_research import research_parse_failure

# ── Случайные User-Agent (реальные браузеры) ──────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Случайные размеры окна как у реальных пользователей
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 1366, "height": 768},
]

# JS для полного скрытия автоматизации
STEALTH_SCRIPT = """
() => {
    // Убираем webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Имитируем плагины
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin' },
            { name: 'Chrome PDF Viewer' },
            { name: 'Native Client' }
        ]
    });

    // Языки как у русского пользователя
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ru-RU', 'ru', 'en-US', 'en']
    });

    // Убираем следы headless
    Object.defineProperty(navigator, 'headless', { get: () => false });

    // Имитируем permissions API
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // Chrome runtime
    window.chrome = { runtime: {} };

    // Реальный размер экрана
    Object.defineProperty(screen, 'availWidth',  { get: () => window.innerWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => window.innerHeight });
}
"""


# ── Извлечение данных из HTML ─────────────────────────────────────────────────

def _parse_price(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    val = int(digits) if digits else None
    return val if val and 10 < val < 10_000_000 else None


def _normalize_image_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    return None


def _image_from_img_tag(img) -> str | None:
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        src = _normalize_image_url(img.get(attr))
        if src:
            return src

    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        for candidate in srcset.split(","):
            src = _normalize_image_url(candidate.strip().split(" ", 1)[0])
            if src:
                return src
    return None


def _is_ozon_blocked_text(text: str) -> bool:
    low = text.lower()
    return any(
        marker in low
        for marker in (
            "доступ ограничен",
            "access denied",
            "captcha",
            "робот",
            "robot",
            "cloudflare",
            "datadome",
            "abt-challenge",
        )
    )


def _extract_ozon_incident_id(text: str) -> str | None:
    match = re.search(r"(?:incident_id=|Инцидент:\s*)([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else None


def _iter_json_values(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_json_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_values(item)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                yield from _iter_json_values(json.loads(stripped))
            except Exception:
                return


def parse_ozon_api_json(payload: dict, url: str) -> dict | None:
    """Извлекает карточку из JSON-ответов Ozon composer/entrypoint API."""
    name_candidates = []
    price = None
    image_url = None
    out_of_stock = False

    name_keys = {"name", "title", "productName", "nameText"}
    price_keys = {"price", "finalPrice", "cardPrice", "currentPrice", "priceWithCard"}
    image_keys = {"image", "imageUrl", "coverImage", "src"}

    for node in _iter_json_values(payload):
        for key, value in node.items():
            if isinstance(value, str):
                text = value.strip()
                low = text.lower()
                if "нет в наличии" in low or "закончился" in low or "товар недоступен" in low:
                    out_of_stock = True

                if key in name_keys and 3 <= len(text) <= 220 and not _is_ozon_blocked_text(text):
                    name_candidates.append(text)

                if not price and key in price_keys:
                    price = _parse_price(text)

                if not image_url and key in image_keys:
                    image_url = _normalize_image_url(text)

            elif not price and key in price_keys and isinstance(value, (int, float)):
                candidate = int(value)
                if 10 < candidate < 10_000_000:
                    price = candidate

    name = None
    for candidate in name_candidates:
        if "ozon" not in candidate.lower():
            name = candidate
            break

    if not name and name_candidates:
        name = re.split(r"\s[|—-]\s", name_candidates[0], maxsplit=1)[0].strip()

    if not name:
        seo = payload.get("seo") if isinstance(payload.get("seo"), dict) else {}
        title = (seo.get("title") or "").strip()
        if title and not _is_ozon_blocked_text(title):
            name = re.split(r"\s[|—-]\s", title, maxsplit=1)[0].strip()

    if not name:
        return None

    availability = "out_of_stock" if out_of_stock and not price else "in_stock" if price else "out_of_stock"
    return {"name": name, "price": price, "availability": availability, "image_url": image_url}


def _detect_ozon_html_availability(soup: BeautifulSoup, price: int | None) -> str:
    add_to_cart_widgets = soup.select(
        "[data-widget*='webAddToCart'], [data-widget*='addToCart'], [data-widget*='webProductButton']"
    )
    add_to_cart_text = " ".join(widget.get_text(" ", strip=True).lower() for widget in add_to_cart_widgets)
    if re.search(r"\b(в корзину|добавить в корзину|купить)\b", add_to_cart_text):
        return "in_stock"

    stock_widgets = soup.select(
        "[data-widget*='webOutOfStock'], [data-widget*='outOfStock'], "
        "[data-widget*='webAddToCart'], [data-widget*='webPrice'], [data-widget*='webSale']"
    )
    stock_text = " ".join(widget.get_text(" ", strip=True).lower() for widget in stock_widgets)
    if re.search(r"нет в наличии|товар недоступен|закончился|сообщить о поступлении", stock_text):
        return "out_of_stock"

    return "in_stock" if price else "out_of_stock"


def parse_ozon_html(html: str, url: str) -> dict | None:
    """Разбирает HTML страницы товара Озон."""
    soup = BeautifulSoup(html, "lxml")

    # Проверка на страницу блокировки
    if _is_ozon_blocked_text(html):
        logger.warning(f"Озон заблокировал запрос: {url}")
        return None

    # Название (h1 иногда грузится позже/прячется; берём запасные варианты)
    name = None
    h1 = soup.select_one("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        og = soup.select_one("meta[property='og:title'], meta[name='og:title']")
        if og and og.get("content"):
            name = og.get("content", "").strip()
    if not name:
        title = soup.select_one("title")
        if title:
            name = title.get_text(strip=True)
    if not name:
        logger.warning(f"Нет h1/title — возможно блокировка: {url}")
        return None
    if len(name) < 3:
        return None

    # Цена
    price = None
    for sel in [
        "div[data-widget='webPrice'] span",
        "div[data-widget='webPrice'] div",
        "span[class*='price']",
        "div[class*='price']",
        "span[class*='Price']",
    ]:
        for elem in soup.select(sel):
            p = _parse_price(elem.get_text(strip=True))
            if p:
                price = p
                break
        if price:
            break

    # Наличие
    blocked_text = soup.find(string=re.compile(
        r"доступ ограничен", re.I
    ))
    if blocked_text:
        return None  # страница блокировки
    availability = _detect_ozon_html_availability(soup, price)

    # Изображение
    image_url = None
    for sel in [
        "div[data-widget='webGallery'] img",
        "div[data-widget='photoShowcase'] img",
        "img[data-widget='image']",
    ]:
        img = soup.select_one(sel)
        if img:
            src = _image_from_img_tag(img)
            if src:
                image_url = src
                break

    return {"name": name, "price": price, "availability": availability, "image_url": image_url}


# ── Ninja браузер ─────────────────────────────────────────────────────────────

class OzonUpdater:
    """🥷 Парсер Озона с максимальной маскировкой."""

    def __init__(self, db: Database, proxy: str = None):
        """
        db    — экземпляр Database
        proxy — строка вида 'http://user:pass@ip:port' или None
        """
        self.db = db
        self.proxy = proxy
        self._pw = None
        self._browser = None
        self._context = None
        self._ua = None
        self._vp = None
        self._launch_args = None
        self._profile_dir = None
        self._last_ozon_api_blocked = False
        self._current_product_id = None
        self.last_blocked_count = 0

    async def _record_attempt(
        self,
        *,
        url: str,
        source: str,
        status: str,
        latency_ms: int,
        http_status: int | None = None,
        error: Exception | None = None,
        trigger: str | None = None,
        strategy: str | None = None,
        cooldown_sec: int = 0,
    ) -> None:
        try:
            await self.db.record_scrape_attempt(
                product_id=self._current_product_id,
                url=url,
                marketplace="ozon",
                source=source,
                status=status,
                http_status=http_status,
                latency_ms=latency_ms,
                error_class=type(error).__name__ if error else None,
                error_text=str(error) if error else None,
                trigger=trigger,
                proxy=self.proxy,
                browser_profile=self._profile_dir,
                strategy=strategy,
                cooldown_sec=cooldown_sec,
            )
        except Exception:
            pass

    async def _recommend_strategy(self, marketplace: str, url: str) -> dict:
        default = {
            "strategy": "normal",
            "skip": False,
            "skip_browser": False,
            "reason": "",
            "cooldown_sec": 0,
        }
        try:
            recommend = getattr(self.db, "recommend_scrape_strategy", None)
            if not recommend:
                return default
            decision = await recommend(marketplace, url=url)
            return {**default, **(decision or {})}
        except Exception as e:
            logger.debug(f"adaptive strategy unavailable: {e}")
            return default

    def _debug_dir(self) -> Path:
        p = Path(os.getenv("PARSER_DEBUG_DIR", "app/data/debug"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def _dump_debug(self, page, prefix: str):
        """
        Пишем скриншот + HTML при подозрении на антибот.
        """
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", prefix)[:80]
            base = self._debug_dir() / f"{ts}_{safe}"
            await page.screenshot(path=str(base) + ".png", full_page=True)
            html = await page.content()
            (Path(str(base) + ".html")).write_text(html, encoding="utf-8")
        except Exception:
            pass

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()

        headless_env = os.getenv("OZON_HEADLESS", "").strip()
        headless = not (headless_env in {"0", "false", "False", "no", "NO"})
        profile_dir = os.getenv("OZON_PROFILE_DIR", "").strip()

        # В рамках одной сессии держим один UA/viewport (как “реальный пользователь”)
        self._ua = random.choice(USER_AGENTS)
        self._vp = random.choice(VIEWPORTS)

        launch_args = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--start-maximized",
                "--lang=ru-RU",
            ],
        }
        # Прокси на уровне браузера
        if self.proxy:
            if not proxy_is_reachable(self.proxy):
                logger.warning(f"Прокси недоступен (не слушает порт): {self.proxy}. Запускаю без прокси.")
                self.proxy = None
            else:
                launch_args["proxy"] = {"server": self.proxy}

        self._launch_args = launch_args
        self._profile_dir = profile_dir
        return self

    async def _ensure_browser(self):
        if self._context or self._browser:
            return
        if not self._pw:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()

        profile_dir = self._profile_dir or ""
        launch_args = self._launch_args or {"headless": True}

        if profile_dir:
            # Persistent context = “реальный профиль” (с куками/локалсторажем)
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                **launch_args,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                user_agent=self._ua,
                viewport=self._vp,
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            await self._context.add_init_script(STEALTH_SCRIPT)
            logger.info(
                f"🥷 Браузер запущен {'с прокси ' + self.proxy if self.proxy else '(без прокси)'} (persistent)"
            )
        else:
            self._browser = await self._pw.chromium.launch(**launch_args)
            logger.info(f"🥷 Браузер запущен {'с прокси ' + self.proxy if self.proxy else '(без прокси)'}")

    async def __aexit__(self, *args):
        browser_started = bool(self._context or self._browser)
        try:
            if self._context:
                await self._context.close()
        except Exception as e:
            logger.warning(f"Playwright context close failed: {e}")
        finally:
            self._context = None

        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.warning(f"Playwright browser close failed: {e}")
        finally:
            self._browser = None

        try:
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            logger.warning(f"Playwright stop failed: {e}")
        finally:
            self._pw = None
        if browser_started:
            logger.info("Браузер остановлен")

    async def _human_delay(self, min_s: float = None, max_s: float = None):
        """Случайная задержка как у человека."""
        lo = min_s or DELAY_MIN
        hi = max_s or DELAY_MAX
        await asyncio.sleep(random.uniform(lo, hi))

    async def _human_scroll(self, page):
        """Имитирует плавный скролл страницы вниз и обратно."""
        try:
            # Скроллим вниз несколькими шагами
            for _ in range(random.randint(3, 6)):
                await page.mouse.wheel(0, random.randint(200, 500))
                await asyncio.sleep(random.uniform(0.3, 0.8))
            # Немного вверх
            await page.mouse.wheel(0, -random.randint(100, 300))
            await asyncio.sleep(random.uniform(0.2, 0.5))
        except Exception:
            pass

    async def _move_mouse_randomly(self, page):
        """Случайное движение мыши."""
        try:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, vp["width"] - 100)
                y = random.randint(100, vp["height"] - 100)
                await page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.1, 0.4))
        except Exception:
            pass

    async def _warm_visible_assets(self, page) -> None:
        """Give lazy-loaded marketplace images a chance to request and render."""
        try:
            await page.wait_for_load_state("load", timeout=20_000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass

        for _ in range(6):
            try:
                await page.mouse.wheel(0, random.randint(600, 900))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.6, 1.0))

        for _ in range(2):
            try:
                await page.mouse.wheel(0, -random.randint(500, 800))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.4, 0.8))

        try:
            await page.wait_for_function(
                """() => Array.from(document.images)
                    .filter((img) => {
                        const rect = img.getBoundingClientRect();
                        return rect.width > 40 && rect.height > 40;
                    })
                    .some((img) => img.complete && img.naturalWidth > 0)""",
                timeout=10_000,
            )
        except Exception:
            logger.debug("No fully loaded visible images detected before parsing")

    def _api_urls(self, url: str) -> list[str]:
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        encoded = quote(path, safe="")
        return [
            f"https://www.ozon.ru/api/composer-api.bx/page/json/v2?url={encoded}",
            f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={encoded}",
        ]

    async def _fetch_via_api(self, url: str) -> dict | None:
        """Пробует получить карточку через JSON API Ozon до запуска тяжёлого рендера."""
        self._last_ozon_api_blocked = False
        api_statuses = []
        headers = {
            "User-Agent": self._ua or random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.ozon.ru/",
            "Origin": "https://www.ozon.ru",
        }
        request_proxy = self.proxy
        if request_proxy and request_proxy.startswith(("socks5://", "socks4://", "socks5h://")):
            request_proxy = None

        async with aiohttp.ClientSession(headers=headers) as session:
            for api_url in self._api_urls(url):
                t0 = perf_counter()
                try:
                    async with session.get(
                        api_url,
                        timeout=aiohttp.ClientTimeout(total=15),
                        proxy=request_proxy,
                    ) as resp:
                        latency_ms = int((perf_counter() - t0) * 1000)
                        text = await resp.text()
                        if resp.status != 200:
                            if resp.status in {403, 429}:
                                api_statuses.append(resp.status)
                            logger.warning(f"Ozon API {api_url}: status {resp.status}")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="blocked" if resp.status in {403, 429} else "http_error",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                                trigger=f"http_{resp.status}" if resp.status in {403, 429} else None,
                            )
                            continue
                        if _is_ozon_blocked_text(text):
                            api_statuses.append("blocked")
                            incident = _extract_ozon_incident_id(text)
                            logger.warning("Ozon API вернул антибот/challenge")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="blocked",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                                trigger="abt-challenge",
                                strategy=f"incident={incident}" if incident else None,
                            )
                            continue
                        try:
                            payload = json.loads(text)
                        except Exception:
                            logger.warning("Ozon API вернул не JSON")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="parse_error",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                            )
                            continue
                        data = parse_ozon_api_json(payload, url)
                        if data:
                            logger.info(f"Ozon API: карточка получена без браузера: {data['name'][:80]}")
                            await self._record_attempt(
                                url=url,
                                source="api",
                                status="ok",
                                http_status=resp.status,
                                latency_ms=latency_ms,
                            )
                            return data
                        await self._record_attempt(
                            url=url,
                            source="api",
                            status="parse_error",
                            http_status=resp.status,
                            latency_ms=latency_ms,
                        )
                except Exception as e:
                    logger.warning(f"Ozon API ошибка: {e}")
                    await self._record_attempt(
                        url=url,
                        source="api",
                        status="error",
                        latency_ms=int((perf_counter() - t0) * 1000),
                        error=e,
                    )

        if api_statuses and all(status in {403, 429, "blocked"} for status in api_statuses):
            self._last_ozon_api_blocked = True

        return None

    async def _fetch(self, url: str) -> str | None:
        """Открывает страницу как человек, возвращает HTML."""
        fetch_t0 = perf_counter()
        await self._ensure_browser()
        ctx = None
        if self._context:
            page = await self._context.new_page()
        else:
            ctx = await self._browser.new_context(
                user_agent=self._ua or random.choice(USER_AGENTS),
                viewport=self._vp or random.choice(VIEWPORTS),
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            await ctx.add_init_script(STEALTH_SCRIPT)
            page = await ctx.new_page()
        try:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    # Сначала заходим на главную Озона (как настоящий пользователь)
                    if attempt == 0:
                        await page.goto("https://www.ozon.ru/", wait_until="domcontentloaded", timeout=20_000)
                        await self._human_delay(2, 4)
                        await self._move_mouse_randomly(page)

                    # Теперь идём на нужную страницу
                    await page.goto(url, wait_until="load", timeout=60_000)

                    # Даём странице догрузить XHR/скрипты (Ozon часто рендерит клиентом)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        pass

                    # Ждём признаки того, что страница реально отрендерилась
                    try:
                        await page.wait_for_selector(
                            "h1, title, meta[property='og:title']",
                            state="attached",
                            timeout=18_000,
                        )
                    except Exception:
                        current_url = page.url
                        try:
                            t = (await page.title()) or ""
                        except Exception:
                            t = ""
                        logger.warning(
                            f"h1/title не появились (попытка {attempt+1}) url={current_url} title_len={len(t)}"
                        )
                        await self._dump_debug(page, f"ozon_no_title_{attempt+1}")
                        await self._human_delay(3, 6)
                        continue

                    # Имитируем поведение человека
                    await self._human_delay(1.5, 3)
                    await self._move_mouse_randomly(page)
                    await self._human_scroll(page)
                    await self._warm_visible_assets(page)
                    await self._human_delay(1, 2)

                    html = await page.content()
                    low = html.lower()

                    # Проверяем не получили ли блокировку
                    if _is_ozon_blocked_text(low):
                        incident = _extract_ozon_incident_id(html)
                        suffix = f" incident={incident}" if incident else ""
                        logger.warning(
                            f"Блокировка Ozon/abt-challenge на попытке {attempt+1}/{RETRY_ATTEMPTS}{suffix}"
                        )
                        await self._dump_debug(page, f"ozon_blocked_{attempt+1}")
                        if attempt + 1 < RETRY_ATTEMPTS:
                            await self._human_delay(15, 30)
                            continue
                        await self._record_attempt(
                            url=url,
                            source="browser",
                            status="blocked",
                            latency_ms=int((perf_counter() - fetch_t0) * 1000),
                            trigger="abt-challenge",
                            strategy=f"incident={incident}" if incident else None,
                        )
                        return None

                    await self._record_attempt(
                        url=url,
                        source="browser",
                        status="ok",
                        latency_ms=int((perf_counter() - fetch_t0) * 1000),
                    )
                    return html

                except Exception as e:
                    logger.warning(f"Попытка {attempt+1}/{RETRY_ATTEMPTS} ошибка: {e}")
                    await self._dump_debug(page, f"ozon_exception_{attempt+1}")
                    await self._human_delay(5, 10)

            await self._record_attempt(
                url=url,
                source="browser",
                status="error",
                latency_ms=int((perf_counter() - fetch_t0) * 1000),
            )
            return None
        finally:
            try:
                await page.close()
            except Exception:
                pass
            if ctx:
                await ctx.close()

    async def process_url(self, url: str, product_id: int | None = None) -> dict | None:
        """Загружает и парсит одну страницу товара."""
        self._current_product_id = product_id
        decision = await self._recommend_strategy("ozon", url)
        if decision.get("skip"):
            logger.warning(f"Ozon adaptive skip: {decision['reason']} url={url}")
            await self._record_attempt(
                url=url,
                source="strategy",
                status="skipped",
                latency_ms=0,
                trigger="adaptive_skip",
                strategy=decision["strategy"],
                cooldown_sec=decision.get("cooldown_sec", 0),
            )
            self._current_product_id = None
            return None

        api_data = None
        if decision.get("skip_api"):
            logger.warning(f"Ozon adaptive API skip: {decision['reason']} url={url}")
            await self._record_attempt(
                url=url,
                source="api",
                status="skipped",
                latency_ms=0,
                trigger="adaptive_api_cooldown",
                strategy=decision["strategy"],
                cooldown_sec=decision.get("cooldown_sec", 0),
            )
        else:
            api_data = await self._fetch_via_api(url)
        if api_data:
            self._current_product_id = None
            return api_data

        if decision.get("skip_api") and decision.get("skip_browser"):
            await self._record_attempt(
                url=url,
                source="strategy",
                status="skipped",
                latency_ms=0,
                trigger="adaptive_all_routes_cooldown",
                strategy=decision["strategy"],
                cooldown_sec=decision.get("cooldown_sec", 0),
            )
            self._current_product_id = None
            return None

        skip_browser_after_api_block = os.getenv(
            "OZON_SKIP_BROWSER_AFTER_API_BLOCK",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if self._last_ozon_api_blocked and skip_browser_after_api_block:
            logger.warning(f"Ozon заблокировал API для сети/IP, браузерный fallback пропущен: {url}")
            await self._record_attempt(
                url=url,
                source="browser",
                status="skipped",
                latency_ms=0,
                trigger="api_blocked",
                strategy="env_skip_browser_after_api_block",
            )
            self._current_product_id = None
            return None
        if self._last_ozon_api_blocked and decision.get("skip_browser"):
            logger.warning(f"Ozon adaptive browser skip after API block: {decision['reason']} url={url}")
            await self._record_attempt(
                url=url,
                source="browser",
                status="skipped",
                latency_ms=0,
                trigger="adaptive_browser_cooldown",
                strategy=decision["strategy"],
                cooldown_sec=decision.get("cooldown_sec", 0),
            )
            self._current_product_id = None
            return None

        html = await self._fetch(url)
        if not html:
            logger.warning(f"Не удалось загрузить (blocked/empty): {url}")
            try:
                await research_parse_failure(
                    source="ozon_fetch_empty",
                    url=url,
                    detail="Playwright: HTML не получен после всех попыток",
                    marketplace="ozon",
                )
            except Exception as e:
                logger.debug(f"research_parse_failure: {e}")
            self._current_product_id = None
            return None
        data = parse_ozon_html(html, url)
        if not data:
            logger.error(f"Не удалось распарсить (возможно блокировка): {url}")
            await self._record_attempt(
                url=url,
                source="parse",
                status="parse_error",
                latency_ms=0,
            )
            try:
                await research_parse_failure(
                    source="ozon_parse_empty",
                    url=url,
                    detail="HTML есть, но parse_ozon_html вернул None (блокировка/разметка)",
                    marketplace="ozon",
                )
            except Exception as e:
                logger.debug(f"research_parse_failure: {e}")
        self._current_product_id = None
        return data

    async def add_urls(self, urls: list[str], callback=None) -> int:
        """Добавляет новые товары по списку URL."""
        added = 0
        self.last_blocked_count = 0
        for i, url in enumerate(urls, 1):
            logger.info(f"[{i}/{len(urls)}] Парсим: {url}")
            data = await self.process_url(url)
            if data:
                await self.db.save_product(url, data)
                added += 1
                if callback:
                    icon = "✅" if data["availability"] == "in_stock" else "❌"
                    await callback(
                        f"{icon} <b>{data['name'][:60]}</b>\n"
                        f"💰 {data['price']} ₽ | {data['availability']}"
                    )
            else:
                if callback:
                    await callback(f"⚠️ Не удалось получить данные (Озон заблокировал):\n{url}")
            # Случайная пауза между товарами как у человека
            await self._human_delay()
        return added

    async def update_all(self, callback=None) -> tuple[int, list[dict]]:
        """Обновляет цены всех товаров из БД."""
        products = [p for p in await self.db.get_all_products() if "ozon.ru" in p.url]
        logger.info(f"Обновляем {len(products)} товаров")
        updated = 0
        changes = []

        for i, product in enumerate(products, 1):
            logger.info(f"[{i}/{len(products)}] {product.name}")
            data = await self.process_url(product.url, product_id=product.id)

            if data:
                _, price_changed = await self.db.save_product(product.url, data)
                updated += 1
                if price_changed:
                    changes.append({
                        "name": data["name"],
                        "price": data["price"],
                        "availability": data["availability"],
                        "url": product.url,
                    })
                if callback:
                    icon = "✅" if data["availability"] == "in_stock" else "❌"
                    await callback(f"{icon} {data['name'][:50]}: {data['price']} ₽")
            else:
                last = await self.db.get_last_price(product.id)
                if not last or last.availability_status != "blocked":
                    async with self.db.session() as s:
                        s.add(PriceHistory(
                            product_id=product.id,
                            price=None,
                            availability_status="blocked",
                        ))
                        await s.commit()
                logger.warning(f"Временно недоступен (blocked): {product.url}")
                if callback:
                    await callback(f"⚠️ Ozon временно заблокировал: {product.name[:50]}")

            # Случайная пауза между товарами
            await self._human_delay()

        return updated, changes
