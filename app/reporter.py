import io
import json
import base64
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import desc, select

from app.ai_analyzer import PATTERN_ADVICE, calc_price_stats, detect_pattern, simple_forecast
from app.database import Database, PriceHistory, Product, ScrapeAttempt


def _normalize_image_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://", "data:image/")):
        return url
    return None


async def _fetch_image_data_url(session, url: str) -> str | None:
    try:
        async with session.get(url, timeout=12) as resp:
            if resp.status != 200:
                return None
            content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                return None
            data = await resp.read()
            if not data or len(data) > 3_000_000:
                return None
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{content_type};base64,{encoded}"
    except Exception:
        return None


async def _fetch_image_data_url_playwright(url: str) -> str | None:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            request = await pw.request.new_context(
                extra_http_headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": "https://www.ozon.ru/",
                },
                ignore_https_errors=True,
            )
            try:
                response = await request.get(url, timeout=20_000)
                if not response.ok:
                    return None
                content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                if not content_type.startswith("image/"):
                    return None
                data = await response.body()
                if not data or len(data) > 3_000_000:
                    return None
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:{content_type};base64,{encoded}"
            finally:
                await request.dispose()
    except Exception:
        return None


async def embed_report_images(products: list[dict]) -> None:
    import aiohttp

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    semaphore = asyncio.Semaphore(8)

    async def embed_one(product: dict) -> None:
        image_url = product.get("image_url")
        if not image_url or image_url.startswith("data:image/"):
            return
        async with semaphore:
            embedded = await _fetch_image_data_url(session, image_url)
            if not embedded:
                embedded = await _fetch_image_data_url_playwright(image_url)
            if embedded:
                product["image_url"] = embedded

    async with aiohttp.ClientSession(headers=headers) as session:
        await asyncio.gather(*(embed_one(product) for product in products))


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _marketplace(url: str) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low:
        return "yandex_market"
    if "funpay.com" in low:
        return "funpay"
    return "unknown"


def _money(value: int | float | None) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _pct(value: float | int | None) -> str:
    if value is None:
        return "0%"
    return f"{float(value):+.1f}%"


def _sparkline_svg(values: list[int], color: str) -> str:
    if not values:
        return '<svg viewBox="0 0 160 36" class="spark"><path d="" /></svg>'
    if len(values) == 1:
        values = values * 2
    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, 1)
    points = []
    for i, value in enumerate(values):
        x = i * 160 / (len(values) - 1)
        y = 30 - ((value - min_v) / span) * 24
        points.append(f"{x:.1f},{y:.1f}")
    return (
        '<svg viewBox="0 0 160 36" class="spark" aria-hidden="true">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />'
        "</svg>"
    )


async def collect_report_data(db: Database) -> dict:
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)
    since_24h = now - timedelta(hours=24)

    async with db.session() as s:
        products = (await s.execute(select(Product).order_by(desc(Product.last_check)))).scalars().all()
        history_rows = (await s.execute(
            select(PriceHistory, Product)
            .join(Product)
            .where(PriceHistory.recorded_at >= since_30d)
            .order_by(PriceHistory.recorded_at)
        )).all()
        attempts = (await s.execute(
            select(ScrapeAttempt)
            .where(ScrapeAttempt.recorded_at >= since_30d)
            .order_by(desc(ScrapeAttempt.recorded_at))
        )).scalars().all()

    history_by_product: dict[int, list[PriceHistory]] = defaultdict(list)
    for history, _product in history_rows:
        history_by_product[history.product_id].append(history)

    product_cards = []
    status_counter = Counter()
    marketplace_counter = Counter()
    changes_24h = 0
    stale_products = []

    for product in products:
        history = history_by_product.get(product.id, [])
        prices = [h.price for h in history if h.price is not None]
        last = history[-1] if history else None
        marketplace = _marketplace(product.url)
        marketplace_counter[marketplace] += 1
        availability = last.availability_status if last else "unknown"
        status_counter[availability] += 1

        recent_prices = [
            h.price for h in history
            if h.price is not None and (_as_utc(h.recorded_at) or now) >= since_24h
        ]
        if len(set(recent_prices)) > 1:
            changes_24h += 1

        last_check = _as_utc(product.last_check)
        if last_check is None or last_check < since_24h:
            stale_products.append(product)

        if prices:
            stats = calc_price_stats(prices)
            pattern = detect_pattern(prices)
            current_price = stats["current"]
            min_price = stats["min"]
            max_price = stats["max"]
            avg_price = stats["avg"]
            trend_pct = stats["trend_pct"]
            volatility = stats["volatility_pct"]
            forecast_7d = simple_forecast(prices, 7)
            is_deal = current_price <= min_price * 1.03 and max_price > min_price
        else:
            pattern = "unknown"
            current_price = None
            min_price = max_price = avg_price = trend_pct = volatility = forecast_7d = None
            is_deal = False

        product_cards.append({
            "id": product.id,
            "name": product.name or "Без названия",
            "url": product.url,
            "image_url": _normalize_image_url(product.image_url),
            "marketplace": marketplace,
            "current_price": current_price,
            "min_price": min_price,
            "max_price": max_price,
            "avg_price": avg_price,
            "trend_pct": trend_pct or 0,
            "volatility": volatility or 0,
            "pattern": pattern,
            "pattern_label": PATTERN_ADVICE.get(pattern, ("Нет паттерна", ""))[0],
            "availability": availability,
            "forecast_7d": forecast_7d,
            "observations": len(history),
            "prices_history": prices[-18:],
            "last_check": last_check.strftime("%d.%m.%Y %H:%M") if last_check else "нет данных",
            "is_deal": is_deal,
        })

    deals = sorted(
        [p for p in product_cards if p["is_deal"]],
        key=lambda p: ((p["max_price"] or 0) - (p["current_price"] or 0)),
        reverse=True,
    )

    attempts_total = len(attempts)
    attempts_ok = sum(1 for a in attempts if a.status == "ok")
    attempts_blocked = sum(1 for a in attempts if a.status == "blocked")
    attempts_errors = sum(1 for a in attempts if a.status not in {"ok", "blocked", "not_found"})
    success_rate = round((attempts_ok / attempts_total) * 100, 1) if attempts_total else None
    latencies = [a.latency_ms for a in attempts if a.latency_ms is not None]
    avg_latency_ms = round(sum(latencies) / len(latencies)) if latencies else None

    attempts_by_marketplace = Counter(a.marketplace for a in attempts)
    attempts_by_source = Counter(a.source for a in attempts)
    attempts_by_status = Counter(a.status for a in attempts)
    recent_bad_attempts = [
        {
            "time": (_as_utc(a.recorded_at) or now).strftime("%d.%m %H:%M"),
            "marketplace": a.marketplace,
            "source": a.source,
            "status": a.status,
            "http_status": a.http_status,
            "latency_ms": a.latency_ms,
            "url": a.url,
            "error": a.error_text or a.error_class,
        }
        for a in attempts
        if a.status != "ok"
    ][:12]

    hourly = [0] * 24
    for history, _product in history_rows:
        recorded_at = _as_utc(history.recorded_at)
        if recorded_at:
            hourly[recorded_at.hour] += 1

    return {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "period_label": "последние 30 дней",
        "total_products": len(products),
        "marketplaces": dict(marketplace_counter),
        "availability": dict(status_counter),
        "changes_24h": changes_24h,
        "stale_products": [
            {"name": p.name or "Без названия", "url": p.url, "last_check": p.last_check.strftime("%d.%m.%Y %H:%M") if p.last_check else "нет данных"}
            for p in stale_products[:10]
        ],
        "products": product_cards,
        "hourly_activity": hourly,
        "deals": deals[:8],
        "parse_stats": {
            "total": attempts_total,
            "success": attempts_ok,
            "blocked": attempts_blocked,
            "errors": attempts_errors,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency_ms,
            "by_marketplace": dict(attempts_by_marketplace),
            "by_source": dict(attempts_by_source),
            "by_status": dict(attempts_by_status),
            "recent_bad_attempts": recent_bad_attempts,
        },
    }


def generate_html_report(data: dict) -> str:
    products = data["products"]
    parse_stats = data["parse_stats"]
    max_hourly = max(data["hourly_activity"] or [1]) or 1
    max_status = max(parse_stats["by_status"].values() or [1])

    cards_html = "\n".join(_render_product_card(product) for product in products)
    if not cards_html:
        cards_html = '<div class="empty">Товаров пока нет. Добавьте ссылки через /add и запустите /update.</div>'

    deals_html = "\n".join(_render_deal(deal) for deal in data["deals"])
    if not deals_html:
        deals_html = '<div class="note info">Сделок на минимуме цены пока нет. Нужна история наблюдений.</div>'

    bad_attempts_html = "\n".join(_render_bad_attempt(row) for row in parse_stats["recent_bad_attempts"])
    if not bad_attempts_html:
        bad_attempts_html = '<tr><td colspan="6" class="muted">Ошибок и блокировок за период не найдено.</td></tr>'

    stale_html = "\n".join(
        f'<li><a href="{escape(row["url"])}">{escape(row["name"][:90])}</a><span>{escape(row["last_check"])}</span></li>'
        for row in data["stale_products"]
    )
    if not stale_html:
        stale_html = '<li><span>Просроченных проверок нет.</span><span>OK</span></li>'

    hourly_html = "\n".join(
        f'<div class="hour" title="{hour:02d}:00 - {count} записей" style="--alpha:{0.12 + (count / max_hourly) * 0.78:.2f}"></div>'
        for hour, count in enumerate(data["hourly_activity"])
    )

    source_html = _render_distribution(parse_stats["by_source"], "source")
    market_html = _render_distribution(parse_stats["by_marketplace"], "market")
    status_html = "\n".join(
        f'<div class="bar-row"><span>{escape(status)}</span><div><b style="width:{round(count / max_status * 100)}%"></b></div><strong>{count}</strong></div>'
        for status, count in sorted(parse_stats["by_status"].items())
    ) or '<div class="muted">Измерения не найдены</div>'

    products_json = escape(json.dumps(products, ensure_ascii=False), quote=False)

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчёт мониторинга цен - {escape(data['generated_at'])}</title>
<style>
:root {{
  --bg:#f5f7fb; --panel:#ffffff; --line:#dfe5ee; --text:#1c2533; --muted:#667085;
  --blue:#2563eb; --violet:#7c3aed; --green:#059669; --red:#dc2626; --amber:#d97706; --slate:#334155;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, "Segoe UI", Arial, sans-serif; }}
a {{ color:inherit; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 18px 40px; }}
.top {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-bottom:18px; }}
h1 {{ margin:0; font-size:28px; line-height:1.15; letter-spacing:0; }}
.sub {{ color:var(--muted); margin-top:7px; font-size:14px; }}
.stamp {{ padding:8px 12px; border:1px solid var(--line); border-radius:8px; background:var(--panel); font-size:12px; color:var(--muted); white-space:nowrap; }}
.metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0; }}
.metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:15px; min-height:104px; }}
.metric small {{ display:block; color:var(--muted); font-size:12px; margin-bottom:8px; }}
.metric b {{ display:block; font-size:28px; line-height:1; }}
.metric span {{ display:block; color:var(--muted); font-size:12px; margin-top:8px; }}
.grid {{ display:grid; grid-template-columns:1.15fr .85fr; gap:14px; }}
.section {{ margin-top:16px; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
h2 {{ margin:0 0 12px; font-size:15px; text-transform:uppercase; letter-spacing:.04em; color:var(--slate); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(315px,1fr)); gap:12px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
.thumb {{ position:relative; display:flex; width:100%; aspect-ratio:4/3; margin-bottom:10px; border:1px solid var(--line); border-radius:7px; overflow:hidden; background:linear-gradient(135deg,#f8fafc,#eef2f7); color:inherit; text-decoration:none; }}
.thumb img {{ position:absolute; inset:0; z-index:2; display:block; width:100%; height:100%; object-fit:contain; padding:8px; background:#fff; }}
.thumb-fallback {{ position:absolute; inset:0; z-index:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; padding:16px; text-align:center; }}
.thumb-fallback b {{ font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--slate); }}
.thumb-fallback span {{ font-size:12px; color:var(--muted); line-height:1.35; max-width:92%; }}
.thumb-fallback strong {{ font-size:22px; }}
.thumb.missing {{ border-style:dashed; }}
.image-url {{ display:block; margin-top:-5px; margin-bottom:9px; color:var(--muted); font-size:11px; word-break:break-all; }}
.card-head {{ display:flex; justify-content:space-between; gap:10px; margin-bottom:10px; }}
.name {{ font-size:14px; font-weight:650; line-height:1.35; text-decoration:none; }}
.badge {{ flex:0 0 auto; height:24px; border-radius:999px; padding:4px 8px; font-size:11px; font-weight:700; }}
.ozon {{ background:#e8f0ff; color:var(--blue); }} .wildberries {{ background:#f1e8ff; color:var(--violet); }} .unknown,.funpay {{ background:#eef2f7; color:var(--slate); }}
.price {{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; margin-bottom:8px; }}
.price strong {{ font-size:24px; }} .price em {{ font-style:normal; color:var(--muted); font-size:12px; }}
.trend-up {{ color:var(--red); }} .trend-down {{ color:var(--green); }}
.spark {{ width:100%; height:38px; margin:2px 0 8px; background:#f8fafc; border-radius:6px; }}
.meta {{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; color:var(--muted); font-size:12px; }}
.meta b {{ display:block; color:var(--text); font-size:13px; }}
.deal {{ border-left:4px solid var(--green); }}
.deal-line {{ display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-top:1px solid var(--line); }}
.deal-line:first-child {{ border-top:0; padding-top:0; }}
.deal-line a {{ font-weight:650; text-decoration:none; }}
.deal-line span {{ color:var(--muted); font-size:12px; }}
.hours {{ display:grid; grid-template-columns:repeat(24,1fr); gap:4px; margin-top:8px; }}
.hour {{ height:32px; border-radius:4px; background:rgba(37,99,235,var(--alpha)); }}
.axis {{ display:flex; justify-content:space-between; color:var(--muted); font-size:11px; margin-top:6px; }}
.bar-row {{ display:grid; grid-template-columns:92px 1fr 42px; gap:10px; align-items:center; font-size:13px; margin:9px 0; }}
.bar-row div {{ height:8px; background:#eef2f7; border-radius:999px; overflow:hidden; }}
.bar-row b {{ display:block; height:100%; background:var(--blue); }}
.dist {{ display:flex; flex-wrap:wrap; gap:8px; }}
.pill {{ border:1px solid var(--line); border-radius:999px; padding:7px 10px; font-size:12px; background:#fafbfc; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ text-align:left; border-top:1px solid var(--line); padding:9px 7px; vertical-align:top; }}
th {{ color:var(--muted); font-weight:650; }}
.bad {{ color:var(--red); font-weight:650; }}
.muted {{ color:var(--muted); }}
.note {{ border-radius:8px; padding:12px 14px; font-size:13px; }}
.info {{ background:#eff6ff; border:1px solid #bfdbfe; }}
.watch {{ list-style:none; margin:0; padding:0; }}
.watch li {{ display:flex; justify-content:space-between; gap:12px; border-top:1px solid var(--line); padding:9px 0; font-size:13px; }}
.watch li:first-child {{ border-top:0; }}
.watch span {{ color:var(--muted); white-space:nowrap; }}
.footer {{ color:var(--muted); text-align:center; font-size:12px; padding:26px 0 6px; }}
.empty {{ padding:18px; color:var(--muted); background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
@media (max-width:850px) {{ .metrics,.grid {{ grid-template-columns:1fr; }} .top {{ display:block; }} .stamp {{ display:inline-block; margin-top:12px; }} }}
</style>
</head>
<body>
<main class="wrap">
  <div class="top">
    <div>
      <h1>Отчёт мониторинга цен</h1>
      <div class="sub">Период: {escape(data['period_label'])}. Данные собраны из базы parser_agent.</div>
    </div>
    <div class="stamp">Сгенерировано: {escape(data['generated_at'])}</div>
  </div>

  <section class="metrics">
    <div class="metric"><small>Товаров в мониторинге</small><b>{data['total_products']}</b><span>{escape(', '.join(f'{k}: {v}' for k, v in data['marketplaces'].items()) or 'маркетплейсы не найдены')}</span></div>
    <div class="metric"><small>Успешность парсинга</small><b>{parse_stats['success_rate'] if parse_stats['success_rate'] is not None else '—'}%</b><span>{parse_stats['success']} OK из {parse_stats['total']} попыток</span></div>
    <div class="metric"><small>Средняя задержка</small><b>{parse_stats['avg_latency_ms'] if parse_stats['avg_latency_ms'] is not None else '—'} мс</b><span>по scrape_attempts</span></div>
    <div class="metric"><small>Изменений за 24 часа</small><b>{data['changes_24h']}</b><span>{len(data['deals'])} потенциальных сделок</span></div>
  </section>

  <section class="section grid">
    <div class="panel">
      <h2>Состояние парсинга</h2>
      {status_html}
      <div style="height:10px"></div>
      <h2>Источники</h2>
      {source_html}
      <div style="height:10px"></div>
      <h2>Маркетплейсы в попытках</h2>
      {market_html}
    </div>
    <div class="panel">
      <h2>Активность по часам</h2>
      <div class="hours">{hourly_html}</div>
      <div class="axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
    </div>
  </section>

  <section class="section grid">
    <div class="panel">
      <h2>Лучшие возможности</h2>
      {deals_html}
    </div>
    <div class="panel">
      <h2>Требуют внимания</h2>
      <ul class="watch">{stale_html}</ul>
    </div>
  </section>

  <section class="section">
    <h2>Карточки товаров</h2>
    <div class="cards">{cards_html}</div>
  </section>

  <section class="section panel">
    <h2>Последние блокировки и ошибки</h2>
    <table>
      <thead><tr><th>Время</th><th>Маркет</th><th>Источник</th><th>Статус</th><th>HTTP</th><th>Задержка</th></tr></thead>
      <tbody>{bad_attempts_html}</tbody>
    </table>
  </section>

  <script type="application/json" id="report-data">{products_json}</script>
  <div class="footer">parser_agent · HTML-отчёт можно пересылать и открывать без доступа к проекту</div>
</main>
</body>
</html>"""


def _render_product_card(product: dict) -> str:
    color = "#059669" if product["trend_pct"] <= 0 else "#dc2626"
    trend_class = "trend-down" if product["trend_pct"] <= 0 else "trend-up"
    spark = _sparkline_svg(product["prices_history"], color)
    card_class = "card deal" if product["is_deal"] else "card"
    availability = {
        "in_stock": "в наличии",
        "out_of_stock": "нет в наличии",
        "blocked": "блокировка",
        "deleted": "удалён",
    }.get(product["availability"], product["availability"])
    fallback = (
        f'<span class="thumb-fallback"><b>{escape(product["marketplace"])}</b>'
        f'<strong>{_money(product["current_price"])}</strong>'
        f'<span>{escape(product["name"][:70])}</span></span>'
    )
    image = (
        f'<a class="thumb missing" href="{escape(product["url"])}" target="_blank" rel="noreferrer">'
        f"{fallback}</a>"
    )
    if product.get("image_url"):
        image = (
            f'<a class="thumb" href="{escape(product["url"])}" target="_blank" rel="noreferrer">'
            f"{fallback}"
            f'<img src="{escape(product["image_url"])}" alt="{escape(product["name"][:80])}" '
            'loading="lazy" '
            'onerror="this.parentElement.classList.add(\'missing\'); this.remove()">'
            "</a>"
            f'<a class="image-url" href="{escape(product["image_url"])}" target="_blank" rel="noreferrer">image source</a>'
        )
    return f"""
    <article class="{card_class}">
      {image}
      <div class="card-head">
        <a class="name" href="{escape(product['url'])}">{escape(product['name'][:120])}</a>
        <span class="badge {escape(product['marketplace'])}">{escape(product['marketplace'])}</span>
      </div>
      <div class="price">
        <strong>{_money(product['current_price'])}</strong>
        <em class="{trend_class}">{_pct(product['trend_pct'])}</em>
        {'<em>сделка</em>' if product['is_deal'] else ''}
      </div>
      {spark}
      <div class="meta">
        <span><b>{escape(availability)}</b>статус</span>
        <span><b>{_money(product['min_price'])}</b>минимум</span>
        <span><b>{_money(product['max_price'])}</b>максимум</span>
        <span><b>{product['observations']}</b>точек</span>
        <span><b>{_money(product['forecast_7d'])}</b>прогноз 7д</span>
        <span><b>{escape(product['last_check'])}</b>проверка</span>
      </div>
    </article>"""


def _render_deal(deal: dict) -> str:
    saving = (deal["max_price"] or 0) - (deal["current_price"] or 0)
    saving_pct = round(saving / deal["max_price"] * 100, 1) if deal["max_price"] else 0
    return f"""
    <div class="deal-line">
      <div>
        <a href="{escape(deal['url'])}">{escape(deal['name'][:95])}</a>
        <span>Экономия {_money(saving)} относительно максимума</span>
      </div>
      <strong>{saving_pct}%</strong>
    </div>"""


def _render_distribution(items: dict, css_prefix: str) -> str:
    if not items:
        return '<div class="muted">Измерения не найдены</div>'
    return '<div class="dist">' + "".join(
        f'<span class="pill {css_prefix}-{escape(str(key))}">{escape(str(key))}: <b>{value}</b></span>'
        for key, value in sorted(items.items())
    ) + "</div>"


def _render_bad_attempt(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row['time'])}</td>"
        f"<td>{escape(row['marketplace'])}</td>"
        f"<td>{escape(row['source'])}</td>"
        f"<td class='bad'>{escape(row['status'])}</td>"
        f"<td>{row['http_status'] if row['http_status'] is not None else '-'}</td>"
        f"<td>{row['latency_ms']} мс</td>"
        "</tr>"
    )


async def export_html_report(db: Database, embed_images: bool = False) -> io.BytesIO:
    data = await collect_report_data(db)
    if embed_images:
        await embed_report_images(data["products"])
    html = generate_html_report(data)
    buf = io.BytesIO(html.encode("utf-8"))
    buf.name = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    buf.seek(0)
    return buf
