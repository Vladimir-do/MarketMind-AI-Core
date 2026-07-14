import asyncio
import logging
from typing import TYPE_CHECKING, Callable

from aiogram import Bot, types

from app.config import PROXY
from app.telegram_marketplace_utils import _search_competitors_with_fallback
from app.telegram_url_utils import extract_supported_urls
from app.telegram_card_tasks import (
    build_card_task_from_product as _build_card_task_from_product,
    build_card_task_from_url as _build_card_task_from_url,
)
from app.worker import worker_add_urls

if TYPE_CHECKING:
    from app.database import Database

logger = logging.getLogger(__name__)

MAX_BATCH_CARD_SOURCES = 300


def _split_batch_card_sources(text: str) -> list[str]:
    sources = []
    for line in (text or "").splitlines():
        line = line.strip(" \t-•")
        if not line:
            continue
        urls = extract_supported_urls(line)
        if urls:
            sources.extend(urls)
        elif len(line) >= 4:
            sources.append(line)
    return sources


def _build_card_task_from_product_data(product) -> str:
    lines = [
        f"товар: {product.name or 'Новый товар'}",
        f"бренд: {product.brand or 'Нет бренда'}",
    ]
    if product.category:
        lines.append(f"категория: {product.category}")
    if product.price is not None:
        lines.append(f"цена: {product.price}")
    if product.old_price is not None:
        lines.append(f"старая цена: {product.old_price}")
    if product.discount_pct is not None:
        lines.append(f"скидка: {product.discount_pct}%")
    if product.rating is not None:
        lines.append(f"рейтинг: {product.rating}")
    if product.reviews_count is not None:
        lines.append(f"отзывов: {product.reviews_count}")
    if product.availability:
        lines.append(f"наличие: {product.availability}")
    if product.image_url:
        lines.append(product.image_url)
    lines.append(f"источник: {product.url}")
    lines.append("задача: создать максимально привлекательную карточку товара с сильным SEO, выгодами и понятным описанием")
    return "\n".join(lines)


async def _read_text_document(document: types.Document, *, bot: Bot | None) -> str:
    if bot is None:
        return ""
    telegram_file = await bot.get_file(document.file_id)
    downloaded = await bot.download_file(telegram_file.file_path)
    if downloaded is None:
        return ""
    if hasattr(downloaded, "getvalue"):
        raw = downloaded.getvalue()
    else:
        raw = downloaded.read()
    return raw.decode("utf-8", errors="ignore")


async def generate_ozon_card_files(
    message: types.Message,
    text: str,
    *,
    parser_lock: asyncio.Lock,
    bot: Bot | None,
    get_active_profile: Callable[[int], dict],
):
    from app.card_filler import (
        build_ozon_card_search_query,
        build_ozon_card_draft,
        build_ozon_card_quality_report,
        build_enhanced_ozon_card_draft,
        export_ozon_card_json,
        export_ozon_card_xlsx,
        format_ozon_card_preview,
    )

    profile = get_active_profile(message.chat.id)
    base_draft = build_ozon_card_draft(text)
    competitors = []
    if parser_lock.locked():
        await message.answer("⚠️ Парсер занят, сделаю карточку без анализа конкурентов.")
    else:
        await parser_lock.acquire()
        try:
            search_query = build_ozon_card_search_query(base_draft)
            await message.answer(
                f"🔎 Ищу конкурентов для карточки: <b>{search_query}</b>...",
                parse_mode="HTML",
            )
            competitors = await _search_competitors_with_fallback(search_query, max_per_site=8)
        except Exception as e:
            logger.warning(f"card competitor search failed: {e}")
            await message.answer("⚠️ Конкурентов сейчас не удалось собрать, продолжаю по данным товара.")
        finally:
            parser_lock.release()

    draft = await build_enhanced_ozon_card_draft(text, competitors=competitors, profile=profile)
    quality = build_ozon_card_quality_report(draft)
    quality_lines = [f"Оценка качества: <b>{quality.score}/100</b>"]
    if quality.missing:
        quality_lines.append("Не хватает: " + ", ".join(quality.missing))
    if quality.warnings:
        quality_lines.append("Замечания: " + "; ".join(quality.warnings[:4]))
    await message.answer("\n".join(quality_lines), parse_mode="HTML")
    xlsx = export_ozon_card_xlsx(draft)
    json_buf = export_ozon_card_json(draft)
    await message.answer(format_ozon_card_preview(draft), parse_mode="HTML")
    if bot is None:
        return
    await bot.send_document(
        message.chat.id,
        types.BufferedInputFile(xlsx.read(), filename=xlsx.name),
        caption="XLSX-черновик карточки Ozon для проверки и ручного импорта.",
    )
    await bot.send_document(
        message.chat.id,
        types.BufferedInputFile(json_buf.read(), filename=json_buf.name),
        caption="JSON-черновик под следующий шаг: отправка через Ozon Seller API.",
    )


async def generate_ozon_batch_card_files(
    message: types.Message,
    text: str,
    *,
    parser_lock: asyncio.Lock,
    bot: Bot | None,
    get_active_profile: Callable[[int], dict],
    db: "Database",
):
    from app.card_filler import (
        OzonCardBatchItem,
        build_ozon_card_search_query,
        build_ozon_card_draft,
        build_enhanced_ozon_card_draft,
        export_ozon_cards_batch_json,
        export_ozon_cards_batch_xlsx,
        format_ozon_batch_preview,
    )
    from app.database import url_to_hash

    profile = get_active_profile(message.chat.id)
    sources = _split_batch_card_sources(text)
    if not sources:
        return await message.answer("❌ Не нашёл товаров. Пришлите ссылки или текстовые ТЗ, по одному товару на строку.")
    if len(sources) > MAX_BATCH_CARD_SOURCES:
        return await message.answer(
            f"⚠️ За один прогон беру до {MAX_BATCH_CARD_SOURCES} товаров. "
            "Разбейте список на несколько пачек, чтобы не упереться в лимиты Telegram и Ozon."
        )
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(
        f"🍵 Принял товаров: <b>{len(sources)}</b>. Собираю пакет карточек в тихом режиме, можно идти пить чай.",
        parse_mode="HTML",
    )
    items = []
    try:
        url_sources = [source for source in sources if extract_supported_urls(source)]
        if url_sources:
            async def quiet_notify(_text: str):
                return None

            await worker_add_urls(db, url_sources, quiet_notify, proxy=PROXY if PROXY else None)

        for idx, source in enumerate(sources, 1):
            try:
                task = source
                fallback_message = ""
                source_urls = extract_supported_urls(source)
                if source_urls:
                    product = await db.get_product_by_hash(url_to_hash(source_urls[0]))
                    if not product:
                        task = _build_card_task_from_url(source_urls[0])
                        fallback_message = "Данные восстановлены из URL, проверить вручную"
                    else:
                        last_price = await db.get_last_price(product.id)
                        task = _build_card_task_from_product(product, last_price.price if last_price else None)
                        fallback_message = ""

                base_draft = build_ozon_card_draft(task)
                competitors = []
                try:
                    competitors = await _search_competitors_with_fallback(
                        build_ozon_card_search_query(base_draft),
                        max_per_site=8,
                    )
                except Exception as e:
                    logger.warning(f"batch competitor search failed for {base_draft.name[:80]}: {e}")

                draft = await build_enhanced_ozon_card_draft(task, competitors=competitors, profile=profile)
                missing = []
                if not draft.category_hint:
                    missing.append("категория")
                if not draft.price:
                    missing.append("цена")
                if not draft.images:
                    missing.append("фото")
                if not draft.weight_g:
                    missing.append("вес")
                if not (draft.width_mm and draft.height_mm and draft.depth_mm):
                    missing.append("габариты")
                status = "needs_review" if missing else "ready"
                message_parts = []
                if missing:
                    message_parts.append(", ".join(missing))
                if fallback_message:
                    message_parts.append(fallback_message)
                items.append(OzonCardBatchItem(draft, source, status, "; ".join(message_parts)))
            except Exception as e:
                logger.exception("Ошибка пакетной генерации карточки")
                items.append(OzonCardBatchItem(None, source, "error", str(e)[:300]))
    finally:
        parser_lock.release()

    xlsx = export_ozon_cards_batch_xlsx(items)
    json_buf = export_ozon_cards_batch_json(items)
    await message.answer(format_ozon_batch_preview(items), parse_mode="HTML")
    if bot is None:
        return
    await bot.send_document(
        message.chat.id,
        types.BufferedInputFile(xlsx.read(), filename=xlsx.name),
        caption="Общий XLSX по всей пачке: сводка, карточки, характеристики.",
    )
    await bot.send_document(
        message.chat.id,
        types.BufferedInputFile(json_buf.read(), filename=json_buf.name),
        caption="JSON по всей пачке под будущую автоматическую загрузку через Ozon Seller API.",
    )
