"""
Опциональный «поиск подсказок в интернете» при сбое парсера.

Не чинит код автоматически: только собирает ссылки/фрагменты выдачи,
чтобы быстрее разобраться вручную. Включение: RESEARCH_ON_PARSE_FAILURE=1 в .env
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from app.config import RESEARCH_ON_PARSE_FAILURE, logger

DDG_HTML = "https://html.duckduckgo.com/html/"


def _debug_dir() -> Path:
    import os

    p = Path(os.getenv("PARSER_DEBUG_DIR", "app/data/debug"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _infer_marketplace(url: str | None, marketplace: str | None) -> str:
    mp = (marketplace or "").strip().lower()
    if mp:
        return mp
    if not url:
        return "unknown"
    u = url.lower()
    if "ozon.ru" in u:
        return "ozon"
    if "wildberries" in u or "wb.ru" in u:
        return "wildberries"
    if "aliexpress" in u:
        return "aliexpress"
    return "unknown"


def _search_hint_for_marketplace(mp: str) -> str:
    if mp == "ozon":
        return "playwright ozon antibot abt-challenge python"
    if mp == "wildberries":
        return "wildberries card.wb.ru 403 wbbasket aiohttp python"
    if mp == "aliexpress":
        return "aliexpress anti-bot scraping python"
    return "marketplace web scraping blocked python"


def _search_urls(query: str) -> str:
    q = quote_plus(query)
    return (
        f"https://duckduckgo.com/?q={q}\n"
        f"https://www.google.com/search?q={q}\n"
    )


async def _fetch_ddg_snippets(query: str, max_results: int = 8) -> list[tuple[str, str]]:
    """Пытается получить заголовки+URL из HTML-выдачи DDG (может не сработать из-за антибота)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://html.duckduckgo.com",
        "Referer": "https://html.duckduckgo.com/",
    }
    body = f"q={quote_plus(query)}&b="
    out: list[tuple[str, str]] = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                DDG_HTML,
                data=body.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return out
                html = await resp.text()
    except Exception as e:
        logger.debug(f"research: DDG request failed: {e}")
        return out

    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a.result__a"):
        href = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not href or not title:
            continue
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http"):
            continue
        out.append((title, href))
        if len(out) >= max_results:
            break
    return out


async def research_parse_failure(
    *,
    source: str,
    url: str | None = None,
    detail: str = "",
    marketplace: str | None = None,
    max_snippets: int = 8,
) -> Path | None:
    """
    Пишет markdown-файл с ручными ссылками на поиск и (если получилось) сниппетами DDG.
    """
    if not RESEARCH_ON_PARSE_FAILURE:
        return None

    mp = _infer_marketplace(url, marketplace)
    hint = _search_hint_for_marketplace(mp)

    parts = [source, hint, mp]
    if detail:
        parts.append(re.sub(r"\s+", " ", detail)[:200])
    if url:
        parts.append(url[:120])
    query = " ".join(p for p in parts if p)

    lines = [
        "# Parse failure research",
        f"- time (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- marketplace: `{mp}`",
        f"- source: `{source}`",
        f"- url: `{url}`",
        f"- detail: `{detail}`",
        "",
        "## Поиск вручную (всегда работает)",
        "```",
        _search_urls(query).strip(),
        "```",
        "",
        "## Автоподбор ссылок (DDG HTML, может быть пусто)",
        "",
    ]

    snippets = await _fetch_ddg_snippets(query, max_results=max_snippets)
    if snippets:
        for i, (title, href) in enumerate(snippets, 1):
            lines.append(f"{i}. [{title}]({href})")
    else:
        lines.append("_Выдача не получена (блок/таймаут/разметка изменилась)._")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w.-]+", "_", source)[:40]
    path = _debug_dir() / f"{ts}_research_{safe}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"Подсказки по сбою сохранены: {path}")
    return path
