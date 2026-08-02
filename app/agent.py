"""
agent.py — 🤖 Claude AI агент внутри парсера.
Умеет: анализировать цены, читать отзывы, давать советы,
искать товары по названию на Озоне.
"""
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import select, desc, func

from app.ai_client import ai_is_available, ai_missing_message, ask_ai
from app.config import logger
from app.database import Database, Product, PriceHistory


# ── Получение истории цен для анализа ─────────────────────────────────────────

async def get_price_history_text(db: Database, product: Product, days: int = 30) -> str:
    """Формирует текстовое описание истории цен товара для передачи в Claude."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with db.session() as s:
        rows = (await s.execute(
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .where(PriceHistory.recorded_at >= since)
            .order_by(PriceHistory.recorded_at)
        )).scalars().all()

    if not rows:
        return "Нет данных об истории цен."

    lines = []
    for r in rows:
        date = r.recorded_at.strftime("%d.%m %H:%M")
        price_str = f"{r.price} ₽" if r.price else "недоступен"
        lines.append(f"{date}: {price_str} ({r.availability_status})")

    prices = [r.price for r in rows if r.price]
    if prices:
        lines.append(f"\nМин: {min(prices)} ₽ | Макс: {max(prices)} ₽ | Сейчас: {prices[-1]} ₽")

    return "\n".join(lines)


async def get_all_stats(db: Database) -> dict:
    """Общая статистика базы для агента."""
    async with db.session() as s:
        n_products = await s.scalar(select(func.count(Product.id)))

        # Товары с изменением цены за последние 24ч
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        changed = (await s.execute(
            select(PriceHistory, Product)
            .join(Product)
            .where(PriceHistory.recorded_at >= since)
            .order_by(desc(PriceHistory.recorded_at))
        )).all()

    return {
        "total_products": n_products,
        "recent_changes": [
            {
                "name": p.name,
                "price": ph.price,
                "status": ph.availability_status,
                "time": ph.recorded_at.strftime("%H:%M"),
            }
            for ph, p in changed[:10]
        ]
    }


# ── Claude AI клиент ──────────────────────────────────────────────────────────

class PriceAgent:
    """Агент на базе Claude для анализа цен и товаров."""

    SYSTEM_PROMPT = """Ты — умный ассистент для мониторинга цен на Озоне.
Твои задачи:
- Анализировать историю цен и находить тренды
- Определять лучший момент для покупки
- Предупреждать о подозрительных изменениях цен
- Давать краткие, конкретные советы

Отвечай на русском языке. Будь кратким — не более 5-6 предложений.
Используй эмодзи для наглядности. Не повторяй данные которые уже показаны пользователю."""

    def __init__(self, db: Database):
        self.db = db
        if not ai_is_available():
            logger.warning(ai_missing_message())

    def _is_available(self) -> bool:
        return ai_is_available()

    async def _ask_claude(self, user_message: str) -> str:
        """Отправляет запрос в настроенный AI-провайдер и возвращает ответ."""
        if not self._is_available():
            return ai_missing_message()
        return await ask_ai(user_message, system=self.SYSTEM_PROMPT, max_tokens=1024)

    # ── Анализ конкретного товара ─────────────────────────────────────────────

    async def analyze_product(self, product_id: int) -> str:
        """Анализирует историю цен одного товара и даёт совет."""
        async with self.db.session() as s:
            product = await s.get(Product, product_id)
        if not product:
            return "❌ Товар не найден"

        history = await get_price_history_text(self.db, product, days=30)

        prompt = f"""Товар: {product.name}
URL: {product.url}

История цен за 30 дней:
{history}

Проанализируй динамику цены и дай совет:
1. Текущая цена выгодная или нет?
2. Есть ли тренд (рост/падение)?
3. Стоит ли покупать сейчас или подождать?"""

        return await self._ask_claude(prompt)

    # ── Анализ всего портфеля ─────────────────────────────────────────────────

    async def analyze_portfolio(self) -> str:
        """Анализирует все отслеживаемые товары и выделяет самые интересные."""
        stats = await get_all_stats(self.db)

        if stats["total_products"] == 0:
            return "📭 База пустая — добавьте товары через /add"

        changes_text = ""
        if stats["recent_changes"]:
            lines = []
            for ch in stats["recent_changes"]:
                lines.append(f"- {ch['name'][:40]}: {ch['price']} ₽ ({ch['status']}) в {ch['time']}")
            changes_text = "\n".join(lines)
        else:
            changes_text = "Изменений за последние 24 часа не было"

        prompt = f"""У меня отслеживается {stats['total_products']} товаров на Озоне.

Изменения цен за последние 24 часа:
{changes_text}

Дай краткий итоговый отчёт:
- Есть ли что-то интересное среди изменений?
- На что обратить внимание?
- Общая рекомендация?"""

        return await self._ask_claude(prompt)

    # ── Умный поиск по названию ───────────────────────────────────────────────

    async def build_search_url(self, query: str) -> str:
        """Строит URL поиска на Озоне по запросу."""
        encoded = query.strip().replace(" ", "+")
        return f"https://www.ozon.ru/search/?text={encoded}&from_global=true"

    async def search_advice(self, query: str) -> str:
        """Даёт совет по поисковому запросу."""
        prompt = f"""Пользователь хочет найти на Озоне: "{query}"

Дай краткий совет:
1. Как лучше сформулировать поиск чтобы найти нужное?
2. На что обратить внимание при выборе?
3. Какие характеристики важны для этого товара?"""

        return await self._ask_claude(prompt)

    # ── Анализ подозрительных цен ─────────────────────────────────────────────

    async def detect_anomalies(self) -> list[dict]:
        """Находит товары с подозрительными изменениями цен (>20% за раз)."""
        products = await self.db.get_all_products()
        if not products:
            return []
        product_ids = [product.id for product in products]
        async with self.db.session() as s:
            all_rows = (await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id.in_(product_ids))
                .where(PriceHistory.price.isnot(None))
                .order_by(PriceHistory.product_id, desc(PriceHistory.recorded_at))
            )).scalars().all()

        recent_by_product: dict[int, list[PriceHistory]] = defaultdict(list)
        for row in all_rows:
            bucket = recent_by_product[row.product_id]
            if len(bucket) < 5:
                bucket.append(row)
        anomalies = []

        for product in products:
            rows = recent_by_product.get(product.id, [])
            prices = [r.price for r in rows if r.price]
            if len(prices) >= 2:
                latest = prices[0]
                previous = prices[1]
                if previous > 0:
                    change_pct = abs(latest - previous) / previous * 100
                    if change_pct >= 20:
                        anomalies.append({
                            "name": product.name,
                            "url": product.url,
                            "old_price": previous,
                            "new_price": latest,
                            "change_pct": round(change_pct, 1),
                            "direction": "📉" if latest < previous else "📈",
                        })

        return anomalies

    # ── Нахождение лучших сделок ──────────────────────────────────────────────

    async def find_best_deals(self) -> list[dict]:
        """Находит товары на минимальной цене за 30 дней."""
        products = await self.db.get_all_products()
        deals = []
        since = datetime.now(timezone.utc) - timedelta(days=30)
        if not products:
            return []
        product_ids = [product.id for product in products]
        async with self.db.session() as s:
            all_rows = (await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id.in_(product_ids))
                .where(PriceHistory.recorded_at >= since)
                .where(PriceHistory.price.isnot(None))
                .order_by(PriceHistory.product_id, PriceHistory.recorded_at)
            )).scalars().all()

        history_by_product: dict[int, list[PriceHistory]] = defaultdict(list)
        for row in all_rows:
            history_by_product[row.product_id].append(row)

        for product in products:
            rows = history_by_product.get(product.id, [])
            if len(rows) < 2:
                continue

            prices = [r.price for r in rows]
            current = prices[-1]
            min_price = min(prices)
            max_price = max(prices)

            # Если текущая цена = минимум за 30 дней — хорошая сделка
            if current == min_price and max_price > min_price:
                savings = max_price - min_price
                savings_pct = round(savings / max_price * 100, 1)
                deals.append({
                    "name": product.name,
                    "url": product.url,
                    "current_price": current,
                    "max_price": max_price,
                    "savings": savings,
                    "savings_pct": savings_pct,
                })

        # Сортируем по % выгоды
        deals.sort(key=lambda x: x["savings_pct"], reverse=True)
        return deals[:5]


# ── Анализ отзывов (позитив/негатив/фейк) ────────────────────────────────────

    async def analyze_reviews(self, reviews: list[str], product_name: str) -> str:
        """Анализирует отзывы через Claude — тональность, фейки, резюме."""
        if not reviews:
            return "📭 Отзывов для анализа нет."

        reviews_text = "\n".join(f"- {r[:200]}" for r in reviews[:15])

        prompt = f"""Товар: {product_name}

Отзывы покупателей:
{reviews_text}

Проанализируй отзывы и ответь:
1. 😊 Сколько позитивных, 😐 нейтральных, 😞 негативных?
2. 🚩 Есть ли признаки фейковых отзывов? (одинаковые фразы, слишком восторженные без деталей)
3. 💬 Главные плюсы товара по отзывам (1-2 пункта)
4. ⚠️ Главные минусы (1-2 пункта)
5. 🎯 Итоговый совет: стоит брать?"""

        return await self._ask_claude(prompt)

    async def compare_prices(self, product_name: str, ozon_price: int | None, wb_price: int | None) -> str:
        """Сравнивает цены одного товара на разных маркетплейсах."""
        if not ozon_price and not wb_price:
            return "❌ Нет данных для сравнения."

        prices_info = []
        if ozon_price:
            prices_info.append(f"Озон: {ozon_price} ₽")
        if wb_price:
            prices_info.append(f"Wildberries: {wb_price} ₽")

        diff = ""
        if ozon_price and wb_price:
            cheaper = "Озон" if ozon_price < wb_price else "Wildberries"
            diff_rub = abs(ozon_price - wb_price)
            diff_pct = round(diff_rub / max(ozon_price, wb_price) * 100, 1)
            diff = f"\n{cheaper} дешевле на {diff_rub} ₽ ({diff_pct}%)"

        prompt = f"""Товар: {product_name}
Цены: {', '.join(prices_info)}{diff}

Дай краткий совет где лучше купить.
Учти: на Озоне часто лучше доставка, на WB бывают дополнительные скидки по картам.
Ответ максимум 3 предложения."""

        ai_comment = await self._ask_claude(prompt)
        lines = [f"💰 <b>Сравнение цен: {product_name[:40]}</b>"]
        if ozon_price:
            lines.append(f"🔵 Озон: <b>{ozon_price} ₽</b>")
        if wb_price:
            lines.append(f"🟣 WB: <b>{wb_price} ₽</b>")
        if diff:
            lines.append(diff.strip())
        lines.append(f"\n🤖 {ai_comment}")
        return "\n".join(lines)
