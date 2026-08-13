from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def command_limit(text: str | None, command: str, default: int = 10, max_limit: int = 30) -> int:
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return default

    command_token = parts[0].split("@", 1)[0]
    if command_token != f"/{command}" or len(parts) == 1:
        return default

    try:
        return max(1, min(max_limit, int(parts[1].split()[0])))
    except (TypeError, ValueError):
        return default


def format_dt(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def clip(value, limit: int = 80) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_recent_scrape_attempts(rows: Iterable) -> str:
    rows = list(rows)
    lines = [f"<b>Последние попытки парсинга: {len(rows)}</b>"]
    for item in rows:
        status = html.escape(str(item.status or item.fetch_status or "-"))
        marketplace = html.escape(str(item.marketplace or "-"))
        source = html.escape(str(item.source or "-"))
        http_status = item.http_status if item.http_status is not None else "-"
        latency = item.latency_ms if item.latency_ms is not None else "-"
        error = f" | {html.escape(clip(item.error_class or item.error_text, 70))}" if (item.error_class or item.error_text) else ""
        lines.append(
            f"<code>{html.escape(format_dt(item.recorded_at))}</code> "
            f"{marketplace}/{source} {status} http={http_status} latency={latency}ms{error}"
        )
    return "\n".join(lines)


def format_blocked_patterns(rows: Iterable) -> str:
    rows = list(rows)
    lines = [f"<b>Anti-bot / block memory: {len(rows)}</b>"]
    for item in rows:
        marketplace = html.escape(str(item.marketplace or "-"))
        source = html.escape(str(item.source or "-"))
        status = html.escape(str(item.status or "-"))
        trigger = html.escape(str(item.trigger or "-"))
        strategy = html.escape(str(item.strategy or "-"))
        cooldown = item.cooldown_sec or 0
        url = html.escape(clip(item.url, 70))
        lines.append(
            f"<code>{html.escape(format_dt(item.recorded_at))}</code> "
            f"{marketplace}/{source} {status} trigger={trigger} strategy={strategy} cooldown={cooldown}s\n"
            f"<code>{url}</code>"
        )
    return "\n".join(lines)


def format_marketplace_health(items: Iterable[dict]) -> str:
    lines = ["<b>Marketplace health</b>"]
    for item in items:
        health = item["health"]
        decision = item["decision"]
        circuit_left = item["circuit_left"]
        status = "cooldown" if circuit_left or decision.get("skip") or decision.get("skip_browser") else "ok"
        reason = decision.get("reason") or "-"
        scores = health.get("source_scores", {})
        api_score = scores.get("api", {}).get("score", 0)
        browser_score = scores.get("browser", {}).get("score", 0)
        search_score = scores.get("search_fallback", {}).get("score", 0)
        lines.append(
            f"<b>{html.escape(item['marketplace'])}</b>: {status}, "
            f"heat={health.get('heat_score', 0)}, blocks={health.get('blocks', 0)}, "
            f"cooldown={health.get('dynamic_cooldown_sec', 0)}s, circuit={circuit_left}s, "
            f"strategy={html.escape(str(decision.get('strategy', 'normal')))}, "
            f"scores api/browser/search={api_score}/{browser_score}/{search_score}, "
            f"profile={html.escape(str(health.get('preferred_browser_profile') or '-'))}, "
            f"proxy={html.escape(str(health.get('preferred_proxy') or '-'))}, "
            f"reason={html.escape(str(reason))}"
        )
    return "\n".join(lines)


def format_product_list(products: Iterable, latest_by_product: dict) -> str:
    products = list(products)
    lines = [f"📦 <b>Отслеживается {len(products)} товаров:</b>\n"]
    for product in products:
        last = latest_by_product.get(product.id)
        price_str = f"{last.price} ₽" if last and last.price else "—"
        icon = "✅" if last and last.availability_status == "in_stock" else "❌"
        lines.append(f"{icon} <a href='{product.url}'>{product.name[:50]}</a> — {price_str}")
    return "\n".join(lines)


def format_status_message(n_products: int, n_history: int, n_subscribers: int, ai_available: bool) -> str:
    return (
        f"📊 <b>Статистика</b>\n\n"
        f"Товаров: <b>{n_products}</b>\n"
        f"Записей истории: <b>{n_history}</b>\n"
        f"Подписчиков: <b>{n_subscribers}</b>\n"
        f"AI-агент: {'✅ активен' if ai_available else '❌ нет API ключа'}"
    )


def format_network_diagnostics(
    telegram_proxy: str,
    marketplace_proxy: str,
    dns_result: tuple[bool, str],
    tcp_result: tuple[bool, str],
    https_result: tuple[bool, str],
) -> str:
    dns_ok, dns_msg = dns_result
    tcp_ok, tcp_msg = tcp_result
    https_ok, https_msg = https_result
    lines = [
        "🌐 <b>Сетевая диагностика</b>",
        "",
        f"Telegram proxy: <code>{html.escape(telegram_proxy)}</code>",
        f"Marketplace proxy: <code>{html.escape(marketplace_proxy)}</code>",
        "",
        f"DNS api.telegram.org: {'✅' if dns_ok else '❌'} {html.escape(dns_msg)}",
        f"TCP api.telegram.org:443: {'✅' if tcp_ok else '❌'} {html.escape(tcp_msg)}",
        f"HTTPS api.telegram.org: {'✅' if https_ok else '❌'} {html.escape(https_msg)}",
    ]
    if not (dns_ok and tcp_ok and https_ok):
        lines.extend(
            [
                "",
                "Подсказка: если есть ❌, проверьте VPN/прокси/фаервол и попробуйте снова.",
            ]
        )
    return "\n".join(lines)
