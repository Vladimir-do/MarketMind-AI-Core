from __future__ import annotations

import html

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database import Database


async def build_market_overview_message(db: Database) -> str:
    from app.ai_analyzer import DeepAnalyzer

    analyzer = DeepAnalyzer(db)
    return await analyzer.market_overview()


async def build_price_forecast_message(db: Database) -> str:
    from app.ai_analyzer import DeepAnalyzer, simple_forecast

    analyzer = DeepAnalyzer(db)
    products = await db.get_all_products()

    if not products:
        return "📭 База пустая."

    lines = ["🔮 <b>Прогноз цен на 7 дней:</b>\n"]
    for product in products[:10]:
        prices = await analyzer._get_prices(product.id)
        if len(prices) < 2:
            continue
        current = prices[-1]
        forecast = simple_forecast(prices, 7)
        if not forecast:
            continue
        diff = forecast - current
        arrow = "📉" if diff < 0 else "📈" if diff > 0 else "➡️"
        pct = round(diff / current * 100, 1)
        lines.append(
            f"{arrow} <b>{html.escape(product.name[:45])}</b>\n"
            f"   Сейчас: {current} ₽ → через 7д: {forecast} ₽ ({pct:+.1f}%)"
        )

    if len(lines) == 1:
        return "📭 Недостаточно данных для прогноза. Нужно больше наблюдений."

    return "\n".join(lines)


async def build_price_alerts_message(db: Database) -> str:
    from app.ai_analyzer import DeepAnalyzer

    analyzer = DeepAnalyzer(db)
    alerts = await analyzer.price_alert_check()

    if not alerts:
        return "✅ Активных алертов нет. Все цены в норме."

    lines = [f"🚨 <b>Активные алерты ({len(alerts)}):</b>\n"]
    for alert in alerts:
        lines.append(
            f"{alert['icon']} <b>{html.escape(str(alert['name']))}</b>\n"
            f"   💰 {alert['price']} ₽ — {html.escape(str(alert['message']))}\n"
            f"   <a href='{alert['url']}'>Открыть товар</a>"
        )
    return "\n".join(lines)
