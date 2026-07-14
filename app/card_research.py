import html
import re
from statistics import median

from app.ai_client import ai_is_available, ask_ai


async def build_card_research_report(query: str, competitors: list[dict]) -> str:
    query = (query or "").strip()
    if not competitors:
        return (
            f"🔎 <b>Анализ конкурентов: {html.escape(query)}</b>\n\n"
            "Ничего не найдено. Попробуйте более общий запрос или другое название товара."
        )

    prices = [item["price"] for item in competitors if isinstance(item.get("price"), int)]
    words = _top_words([item.get("name", "") for item in competitors])
    local_report = _build_local_report(query, competitors, prices, words)

    if not ai_is_available():
        return local_report + "\n\n<i>AI недоступен, показан локальный анализ.</i>"

    ai_text = await ask_ai(
        _build_ai_prompt(query, competitors, prices, words),
        system=AI_RESEARCH_SYSTEM_PROMPT,
        max_tokens=1200,
    )
    if not ai_text or ai_text.startswith("AI error:") or "AI недоступен" in ai_text:
        return local_report + f"\n\n<i>{html.escape(ai_text or 'AI не вернул ответ.')}</i>"

    return local_report + "\n\n<b>AI-рекомендации для карточки:</b>\n" + html.escape(ai_text)


AI_RESEARCH_SYSTEM_PROMPT = """Ты эксперт по карточкам товаров на Ozon.
На основе списка конкурентов дай практичные рекомендации для создания карточки.
Не выдумывай факты о товаре. Пиши кратко, структурно, на русском.
Сфокусируйся на SEO-названии, цене, характеристиках, фото и рисках."""


def _build_local_report(query: str, competitors: list[dict], prices: list[int], words: list[tuple[str, int]]) -> str:
    escaped_query = html.escape(query)
    lines = [
        f"🔎 <b>Анализ конкурентов: {escaped_query}</b>",
        f"Найдено товаров: <b>{len(competitors)}</b>",
    ]

    if prices:
        lines.append(
            "Цена: "
            f"мин <b>{min(prices)} ₽</b>, "
            f"медиана <b>{int(median(prices))} ₽</b>, "
            f"макс <b>{max(prices)} ₽</b>"
        )
    else:
        lines.append("Цена: не удалось определить по выдаче")

    if words:
        keyword_text = ", ".join(f"{html.escape(word)} ({count})" for word, count in words[:10])
        lines.append(f"Частые слова: {keyword_text}")

    lines.append("\n<b>Топ конкурентов:</b>")
    for idx, item in enumerate(competitors[:7], 1):
        name = html.escape((item.get("name") or "Без названия")[:90])
        price = f"{item['price']} ₽" if item.get("price") else "цена не определена"
        url = html.escape(item.get("url") or "")
        if url:
            lines.append(f"{idx}. <a href='{url}'>{name}</a> — <b>{price}</b>")
        else:
            lines.append(f"{idx}. {name} — <b>{price}</b>")

    lines.append("\n<b>Что взять в карточку:</b>")
    if words:
        lines.append(f"Название: используйте 3-5 сильных слов из выдачи: {', '.join(html.escape(w) for w, _ in words[:5])}.")
    if prices:
        lines.append(f"Цена: ориентир для старта около медианы, <b>{int(median(prices))} ₽</b>, если товар сопоставим по качеству.")
    lines.append("Фото: главное фото на светлом фоне, плюс 3-5 ракурсов, размер, комплектация, сценарий использования.")
    lines.append("Характеристики: обязательно заполнить материал, цвет, размер, вес, комплектацию и совместимость, если применимо.")
    return "\n".join(lines)


def _build_ai_prompt(query: str, competitors: list[dict], prices: list[int], words: list[tuple[str, int]]) -> str:
    compact = [
        {
            "name": item.get("name"),
            "price": item.get("price"),
            "url": item.get("url"),
        }
        for item in competitors[:10]
    ]
    price_summary = {}
    if prices:
        price_summary = {
            "min": min(prices),
            "median": int(median(prices)),
            "max": max(prices),
        }
    return (
        f"Запрос товара: {query}\n"
        f"Цены: {price_summary}\n"
        f"Частые слова: {words[:15]}\n"
        f"Конкуренты: {compact}\n\n"
        "Дай рекомендации:\n"
        "1. SEO-название до 140 символов.\n"
        "2. Какие характеристики обязательно заполнить.\n"
        "3. Какую цену выбрать и почему.\n"
        "4. Какие фото нужны.\n"
        "5. Какие слова не забыть в описании.\n"
        "6. Какие риски проверить перед публикацией."
    )


def _top_words(names: list[str]) -> list[tuple[str, int]]:
    stop = {
        "для", "или", "без", "при", "под", "над", "товар", "шт", "набор",
        "ozon", "wb", "wildberries", "черный", "белый",
    }
    counts: dict[str, int] = {}
    for name in names:
        for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", (name or "").lower()):
            if word in stop or word.isdigit():
                continue
            counts[word] = counts.get(word, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
