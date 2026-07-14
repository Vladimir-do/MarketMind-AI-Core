"""
ai_analyzer.py — глубокий AI анализ с прогнозом цен.
Использует статистику + Claude для умных выводов.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc

from app.ai_client import ai_is_available, ai_missing_message, ask_ai
from app.config import logger
from app.database import Database, Product, PriceHistory


# ── Статистический анализ (без AI, мгновенно) ─────────────────────────────────

def calc_price_stats(prices: list[int]) -> dict:
    """Базовая статистика по списку цен."""
    if not prices:
        return {}
    n = len(prices)
    avg = sum(prices) / n
    sorted_p = sorted(prices)
    median = sorted_p[n // 2]
    volatility = (max(prices) - min(prices)) / avg * 100 if avg else 0
    trend_pct = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0
    return {
        "min": min(prices),
        "max": max(prices),
        "avg": round(avg),
        "median": median,
        "current": prices[-1],
        "volatility_pct": round(volatility, 1),
        "trend_pct": round(trend_pct, 1),
        "count": n,
    }


def simple_forecast(prices: list[int], days_ahead: int = 7) -> int | None:
    """
    Простой прогноз цены на N дней вперёд методом линейной регрессии.
    Не требует PyTorch — работает на чистом Python.
    """
    if len(prices) < 3:
        return None

    n = len(prices)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(prices) / n

    # Коэффициенты линейной регрессии
    numerator = sum((x[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return prices[-1]

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    forecast = intercept + slope * (n + days_ahead - 1)
    return max(1, round(forecast))


def detect_pattern(prices: list[int]) -> str:
    """Определяет паттерн изменения цены по общему тренду."""
    if len(prices) < 2:
        return "insufficient_data"

    overall_change = (prices[-1] - prices[0]) / prices[0]

    if abs(overall_change) < 0.03:
        return "stable"
    elif overall_change < -0.03:
        return "falling"
    elif overall_change > 0.03:
        return "rising"
    return "volatile"


PATTERN_ADVICE = {
    "rising":   ("📈 Цена растёт", "Если нужен товар — лучше брать сейчас"),
    "falling":  ("📉 Цена падает", "Стоит подождать ещё немного"),
    "stable":   ("➡️ Цена стабильна", "Хорошее время для покупки"),
    "volatile": ("🎢 Цена нестабильна", "Следите за уведомлениями об изменениях"),
    "insufficient_data": ("❓ Мало данных", "Нужно больше наблюдений"),
}


# ── Глубокий AI анализатор ────────────────────────────────────────────────────

class DeepAnalyzer:
    """Объединяет статистику + Claude для максимально умного анализа."""

    def __init__(self, db: Database):
        self.db = db

    async def _claude(self, prompt: str, max_tokens: int = 800) -> str:
        if not ai_is_available():
            return ai_missing_message()
        return await ask_ai(
            prompt,
            max_tokens=max_tokens,
            system=(
                "Ты эксперт по анализу цен на маркетплейсах. "
                "Отвечай кратко, по делу, на русском."
            ),
        )

    async def _get_prices(self, product_id: int, days: int = 30) -> list[int]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.db.session() as s:
            rows = (await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product_id)
                .where(PriceHistory.recorded_at >= since)
                .where(PriceHistory.price.isnot(None))
                .order_by(PriceHistory.recorded_at)
            )).scalars().all()
        return [r.price for r in rows]

    async def full_product_analysis(self, product: Product) -> str:
        """Полный анализ одного товара: статистика + прогноз + AI совет."""
        prices = await self._get_prices(product.id)

        if not prices:
            return f"📭 Нет данных по товару <b>{product.name[:50]}</b>"

        stats = calc_price_stats(prices)
        pattern = detect_pattern(prices)
        pattern_label, pattern_advice = PATTERN_ADVICE[pattern]
        forecast_7 = simple_forecast(prices, 7)
        forecast_30 = simple_forecast(prices, 30)

        # Определяем выгодность текущей цены
        current = stats["current"]
        min_p = stats["min"]
        avg_p = stats["avg"]
        if current <= min_p * 1.05:
            deal_status = "🟢 Цена на минимуме — отличный момент для покупки!"
        elif current <= avg_p:
            deal_status = "🟡 Цена ниже средней — неплохо"
        else:
            deal_status = "🔴 Цена выше средней — лучше подождать"

        # Просим Claude дать развёрнутый совет
        ai_prompt = f"""Товар: {product.name}
Маркетплейс: {"Озон" if "ozon" in product.url else "Wildberries"}

Статистика цен за {stats['count']} наблюдений:
- Текущая: {current} ₽
- Минимум: {min_p} ₽  Максимум: {stats['max']} ₽  Среднее: {avg_p} ₽
- Тренд: {stats['trend_pct']:+.1f}%  Волатильность: {stats['volatility_pct']}%
- Паттерн: {pattern}
- Прогноз на 7 дней: {forecast_7} ₽
- Прогноз на 30 дней: {forecast_30} ₽

Дай:
1. Оценку текущей цены (выгодная/нет и почему)
2. Прогноз что будет с ценой
3. Конкретный совет покупателю (1-2 предложения)"""

        ai_advice = await self._claude(ai_prompt)

        # Формируем красивый ответ
        forecast_str = ""
        if forecast_7:
            arrow = "📉" if forecast_7 < current else "📈"
            forecast_str = f"\n🔮 Прогноз 7 дней: {forecast_7} ₽ {arrow}"
        if forecast_30:
            arrow = "📉" if forecast_30 < current else "📈"
            forecast_str += f"\n🔮 Прогноз 30 дней: {forecast_30} ₽ {arrow}"

        return (
            f"📊 <b>{product.name[:55]}</b>\n"
            f"{'🔵 Озон' if 'ozon' in product.url else '🟣 Wildberries'}\n\n"
            f"💰 Текущая цена: <b>{current} ₽</b>\n"
            f"📉 Мин: {min_p} ₽  📈 Макс: {stats['max']} ₽  ⚖️ Среднее: {avg_p} ₽\n"
            f"{pattern_label} | {deal_status}"
            f"{forecast_str}\n\n"
            f"🤖 <b>AI анализ:</b>\n{ai_advice}"
        )

    async def market_overview(self) -> str:
        """Обзор всего рынка — топ сделок, тренды, аномалии."""
        products = await self.db.get_all_products()
        if not products:
            return "📭 База пустая. Добавьте товары через /add"

        rising, falling, stable, deals = [], [], [], []

        for product in products:
            prices = await self._get_prices(product.id)
            if len(prices) < 2:
                continue
            stats = calc_price_stats(prices)
            pattern = detect_pattern(prices)

            item = {"name": product.name[:40], "price": stats["current"],
                    "trend": stats["trend_pct"], "url": product.url}

            if pattern == "falling":
                falling.append(item)
            elif pattern == "rising":
                rising.append(item)
            else:
                stable.append(item)

            # Лучшие сделки
            if stats["current"] <= stats["min"] * 1.03 and stats["max"] > stats["min"]:
                saving = stats["max"] - stats["current"]
                deals.append({**item, "saving": saving,
                              "saving_pct": round(saving / stats["max"] * 100)})

        deals.sort(key=lambda x: x.get("saving_pct", 0), reverse=True)
        falling.sort(key=lambda x: x["trend"])

        lines = [f"🌍 <b>Обзор рынка</b> | {len(products)} товаров\n"]

        if deals:
            lines.append("💎 <b>Лучшие сделки:</b>")
            for d in deals[:3]:
                lines.append(f"  🔥 {d['name']}: {d['price']} ₽ (-{d['saving_pct']}% от макс)")

        if falling:
            lines.append("\n📉 <b>Цена падает (выгодно ждать):</b>")
            for f in falling[:3]:
                lines.append(f"  ↘️ {f['name']}: {f['price']} ₽ ({f['trend']:+.1f}%)")

        if rising:
            lines.append("\n📈 <b>Цена растёт (берите сейчас):</b>")
            for r in rising[:3]:
                lines.append(f"  ↗️ {r['name']}: {r['price']} ₽ ({r['trend']:+.1f}%)")

        # AI финальный комментарий
        summary_data = f"{len(deals)} сделок, {len(falling)} падают, {len(rising)} растут"
        ai_comment = await self._claude(
            f"Краткий рыночный комментарий: {summary_data} из {len(products)} товаров. "
            f"1-2 предложения что интересного происходит на рынке."
        )
        lines.append(f"\n🤖 {ai_comment}")

        return "\n".join(lines)

    async def price_alert_check(self) -> list[dict]:
        """
        Проверяет все товары и возвращает список алертов:
        - цена упала до исторического минимума
        - цена выросла более чем на 20%
        - товар появился в наличии
        """
        products = await self.db.get_all_products()
        alerts = []

        since = datetime.now(timezone.utc) - timedelta(days=30)
        for product in products:
            prices = await self._get_prices(product.id, days=30)

            if len(prices) < 2:
                continue

            current = prices[-1]
            previous = prices[-2]
            min_30d = min(prices)

            last_row = None
            # last price row is the last element of `prices` but we also need availability_status.
            # We fetch it once more from DB to avoid relying on parallel list ordering.
            async with self.db.session() as s:
                last_row = (await s.execute(
                    select(PriceHistory)
                    .where(PriceHistory.product_id == product.id)
                    .where(PriceHistory.recorded_at >= since)
                    .order_by(desc(PriceHistory.recorded_at))
                    .limit(1)
                )).scalar_one_or_none()

            availability = (last_row.availability_status if last_row else None) or "unknown"
            is_sellable = availability == "in_stock"

            # Алерт: новый минимум (только если товар доступен)
            if is_sellable and current == min_30d and current < previous:
                alerts.append({
                    "type": "new_min",
                    "icon": "🎯",
                    "name": product.name[:50],
                    "price": current,
                    "url": product.url,
                    "message": "Новый минимум цены за 30 дней (товар в наличии)!"
                })

            # Алерт: резкий рост (только если товар доступен)
            elif is_sellable and current > previous * 1.2:
                pct = round((current - previous) / previous * 100)
                alerts.append({
                    "type": "spike",
                    "icon": "⚠️",
                    "name": product.name[:50],
                    "price": current,
                    "url": product.url,
                    "message": f"Цена резко выросла на {pct}% (товар в наличии)!"
                })


        return alerts
