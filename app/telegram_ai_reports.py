from __future__ import annotations

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
        return "рџ“­ Р‘Р°Р·Р° РїСѓСЃС‚Р°СЏ."

    lines = ["рџ”® <b>РџСЂРѕРіРЅРѕР· С†РµРЅ РЅР° 7 РґРЅРµР№:</b>\n"]
    for product in products[:10]:
        prices = await analyzer._get_prices(product.id)
        if len(prices) < 2:
            continue
        current = prices[-1]
        forecast = simple_forecast(prices, 7)
        if not forecast:
            continue
        diff = forecast - current
        arrow = "рџ“‰" if diff < 0 else "рџ“€" if diff > 0 else "вћЎпёЏ"
        pct = round(diff / current * 100, 1)
        lines.append(
            f"{arrow} <b>{product.name[:45]}</b>\n"
            f"   РЎРµР№С‡Р°СЃ: {current} в‚Ѕ в†’ С‡РµСЂРµР· 7Рґ: {forecast} в‚Ѕ ({pct:+.1f}%)"
        )

    if len(lines) == 1:
        return "рџ“­ РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РґР°РЅРЅС‹С… РґР»СЏ РїСЂРѕРіРЅРѕР·Р°. РќСѓР¶РЅРѕ Р±РѕР»СЊС€Рµ РЅР°Р±Р»СЋРґРµРЅРёР№."

    return "\n".join(lines)


async def build_price_alerts_message(db: Database) -> str:
    from app.ai_analyzer import DeepAnalyzer

    analyzer = DeepAnalyzer(db)
    alerts = await analyzer.price_alert_check()

    if not alerts:
        return "вњ… РђРєС‚РёРІРЅС‹С… Р°Р»РµСЂС‚РѕРІ РЅРµС‚. Р’СЃРµ С†РµРЅС‹ РІ РЅРѕСЂРјРµ."

    lines = [f"рџљЁ <b>РђРєС‚РёРІРЅС‹Рµ Р°Р»РµСЂС‚С‹ ({len(alerts)}):</b>\n"]
    for alert in alerts:
        lines.append(
            f"{alert['icon']} <b>{alert['name']}</b>\n"
            f"   рџ’° {alert['price']} в‚Ѕ вЂ” {alert['message']}\n"
            f"   <a href='{alert['url']}'>РћС‚РєСЂС‹С‚СЊ С‚РѕРІР°СЂ</a>"
        )
    return "\n".join(lines)
