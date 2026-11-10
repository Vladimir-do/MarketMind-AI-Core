# @skills: ozon-card-draft-builder, ozon-card-ai-enhancement, card-profile-yaml, card-quality-scoring, card-finalization-pipeline
import hashlib
import html
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import median
from urllib.parse import urlparse

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.ai_client import AIClientError, ai_is_available, ask_ai
from app.config import logger


@dataclass(slots=True)
class OzonCardDraft:
    offer_id: str
    name: str
    description: str
    category_hint: str | None = None
    brand: str = "Нет бренда"
    price: int | None = None
    old_price: int | None = None
    vat: str = "0"
    weight_g: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None
    images: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    ai_notes: str = ""
    competitor_summary: str = ""
    # Competitor photos are reference material only; never treat them as this product's images.
    competitors: list[dict] = field(default_factory=list)
    selling_points: list[str] = field(default_factory=list)
    source_text: str = ""


@dataclass(slots=True)
class OzonCardBatchItem:
    draft: OzonCardDraft | None
    source: str
    status: str
    message: str = ""


@dataclass(slots=True)
class OzonCardQualityReport:
    ready: bool
    score: int
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_ozon_card_draft(task: str) -> OzonCardDraft:
    text = _normalize_b6_notation(_clean(task))
    urls = _extract_urls(text)
    price = _extract_price(text)
    old_price = _extract_old_price(text, price) or (round(price * 1.25) if price else None)
    brand = _extract_value(text, ["бренд", "brand"]) or "Нет бренда"
    category = _extract_value(text, ["категория", "category"]) or _guess_category(text)
    if category:
        category = _map_to_ozon_category_path(category)
    dimensions = _extract_dimensions(text)
    weight = _extract_weight(text)
    title = _build_title(text, brand, category)
    category = _specialize_category_path(text, title, category)
    attributes = _extract_attributes(text)
    keywords = _build_keywords(title, category, attributes, brand)
    selling_points = _build_selling_points(title)
    description = _build_description(
        text, title, brand=brand, category=category, attributes=attributes, selling_points=selling_points
    )

    draft = OzonCardDraft(
        offer_id=_build_offer_id(title),
        name=title,
        description=description,
        category_hint=category,
        brand=brand,
        price=price,
        old_price=old_price,
        weight_g=weight,
        width_mm=dimensions.get("width_mm"),
        height_mm=dimensions.get("height_mm"),
        depth_mm=dimensions.get("depth_mm"),
        images=[url for url in urls if _looks_like_image(url)],
        attributes=attributes,
        keywords=keywords,
        selling_points=selling_points,
        checklist=_build_checklist(price, urls, weight, dimensions),
        source_text=task.strip(),
    )
    return finalize_ozon_card_draft(draft)


def finalize_ozon_card_draft(draft: OzonCardDraft) -> OzonCardDraft:
    draft.name = _normalize_b6_notation(_strip_commercial_terms(_clean(draft.name)))[:140] or draft.name
    draft.description = _normalize_b6_notation(_remove_service_noise(draft.description))
    draft.description = _collapse_description(draft.description)
    draft.category_hint = _normalize_category_hint(draft.category_hint, draft.name)
    draft.brand = _clean(draft.brand) or "Нет бренда"
    draft.keywords = _sanitize_keywords(
        [_normalize_b6_notation(k) for k in draft.keywords],
        brand=draft.brand,
        limit=30,
    )
    draft.selling_points = [_normalize_b6_notation(_remove_service_noise(point)) for point in draft.selling_points]
    draft.selling_points = [point for point in draft.selling_points if point]
    draft.attributes = {
        _normalize_b6_notation(_clean(key)).capitalize()[:80]: _normalize_b6_notation(
            _remove_service_noise(_clean(value))
        )[:300]
        for key, value in draft.attributes.items()
        if _clean(key) and _clean(value)
    }
    if draft.category_hint:
        draft.category_hint = _map_to_ozon_category_path(draft.category_hint)
        draft.category_hint = _specialize_category_path(
            f"{draft.source_text} {draft.name}", draft.name, draft.category_hint
        )
    draft.old_price = (
        draft.old_price if not draft.price or not draft.old_price or draft.old_price > draft.price else None
    )
    if draft.old_price is None and draft.price:
        draft.old_price = round(draft.price * 1.25)
    return draft


def build_ozon_card_quality_report(draft: OzonCardDraft) -> OzonCardQualityReport:
    missing = _draft_missing_fields(draft)
    warnings = []
    notes = []

    if draft.brand == "Нет бренда":
        warnings.append("Бренд не указан или не распознан")
    if draft.old_price and draft.price and draft.old_price <= draft.price:
        warnings.append("Старая цена не больше цены продажи")
    if any(word in (draft.description or "").lower() for word in ["лучший", "гарантируем", "лечеб"]):
        warnings.append("В описании есть рискованные обещания")
    if not draft.images:
        warnings.append("Нет фото товара")
    if (
        draft.category_hint
        and "витамин" in draft.category_hint.lower()
        and not any(
            token in (draft.description or "").lower()
            for token in ("состав", "дозировка", "форма выпуска", "капсул", "таблет")
        )
    ):
        warnings.append("Для БАДов стоит явно указать состав, дозировку и форму выпуска")

    if draft.keywords:
        notes.append(f"SEO-ключей: {len(draft.keywords)}")
    if draft.selling_points:
        notes.append(f"Преимуществ: {len(draft.selling_points)}")
    if draft.attributes:
        notes.append(f"Характеристик: {len(draft.attributes)}")

    score = 100
    score -= 18 * len(missing)
    score -= 6 * len(warnings)

    # Reward good descriptions
    desc_len = len(draft.description or "")
    if desc_len > 200:
        score += 5
    if desc_len > 500:
        score += 3
    # Penalize generic/empty descriptions
    if desc_len < 50:
        score -= 10

    # Reward good keywords
    kw_count = len(draft.keywords)
    if kw_count > 5:
        score += 3
    if kw_count > 10:
        score += 2

    # Reward images present
    if draft.images:
        score += 5

    score = max(0, min(100, score))
    return OzonCardQualityReport(
        ready=not missing and not warnings,
        score=score,
        missing=missing,
        warnings=warnings,
        notes=notes,
    )


async def build_enhanced_ozon_card_draft(
    task: str,
    competitors: list[dict] | None = None,
    profile: dict | None = None,
) -> OzonCardDraft:
    draft = build_ozon_card_draft(task)
    competitors = _filter_relevant_competitors(competitors or [], draft)
    profile = profile or {}
    apply_card_profile(draft, profile)
    _apply_competitor_context(draft, competitors)
    if not ai_is_available():
        draft.ai_notes = "AI не применялся: проверьте AI_PROVIDER и ключ выбранного провайдера."
        _sanitize_supplement_draft(draft)
        return finalize_ozon_card_draft(draft)

    try:
        response = await ask_ai(
            _build_ai_card_prompt(draft, competitors, profile),
            system=AI_CARD_SYSTEM_PROMPT,
            max_tokens=3000,
        )
    except AIClientError:
        draft.ai_notes = "AI-доработка недоступна, черновик собран локально с учетом конкурентов."
        _sanitize_supplement_draft(draft)
        return finalize_ozon_card_draft(draft)
    data = _extract_json_object(response)
    if not data or not _has_usable_ai_card_data(data):
        logger.warning("AI card response did not contain usable JSON fields")
        draft.ai_notes = "AI вернул ответ без пригодных полей карточки; использован локальный черновик."
        _sanitize_supplement_draft(draft)
        return finalize_ozon_card_draft(draft)

    draft.name = _clean_ai_string(data.get("name"), max_len=140) or draft.name
    draft.description = _clean_ai_string(data.get("description"), max_len=4000) or draft.description
    draft.category_hint = _clean_ai_string(data.get("category_hint"), max_len=200) or draft.category_hint
    draft.brand = _clean_ai_string(data.get("brand"), max_len=120) or draft.brand
    draft.attributes.update(_clean_string_dict(data.get("attributes")))
    draft.keywords = _sanitize_keywords(
        _clean_string_list(data.get("keywords"), limit=30) or draft.keywords,
        brand=draft.brand,
    )
    draft.selling_points = _clean_string_list(data.get("selling_points"), limit=4) or draft.selling_points
    draft.checklist = _clean_string_list(data.get("checklist"), limit=12) or draft.checklist
    _sanitize_supplement_draft(draft)
    draft.ai_notes = _clean_ai_string(data.get("notes"), max_len=1200) or "AI улучшил черновик карточки."
    apply_card_profile(draft, profile)
    return finalize_ozon_card_draft(draft)


def build_ozon_import_payload(draft: OzonCardDraft) -> dict:
    item = {
        "offer_id": draft.offer_id,
        "name": draft.name,
        "description": draft.description,
        "barcode": "",
        "price": str(draft.price or ""),
        "old_price": str(draft.old_price or ""),
        "vat": draft.vat,
        "currency_code": "RUB",
        "images": draft.images,
        "weight": draft.weight_g,
        "weight_unit": "g",
        "width": draft.width_mm,
        "height": draft.height_mm,
        "depth": draft.depth_mm,
        "dimension_unit": "mm",
        "attributes": [{"name": key, "value": value} for key, value in sorted(draft.attributes.items())],
    }
    return {
        "endpoint_note": "Черновик под Ozon Seller API. Перед отправкой нужны category_id/type_id и обязательные attribute_id из Ozon.",
        "method": "POST /v3/product/import",
        "items": [item],
    }


def build_ozon_card_search_query(draft: OzonCardDraft) -> str:
    # Search with the core product identity, not color/size/other long-tail
    # attributes: overly specific queries can hide otherwise valid competitors.
    explicit = _extract_value(draft.source_text, ["товар", "название товара", "название", "product", "product name"])
    query = _strip_commercial_terms(explicit or draft.name)
    if not query and draft.category_hint:
        query = _strip_commercial_terms(draft.category_hint.split("/")[-1])
    # Do not append the seller's own brand: competitor research must surface
    # competing brands in the same category, not only other SKUs of this brand.
    return query or draft.name


def export_ozon_card_json(draft: OzonCardDraft) -> io.BytesIO:
    payload = {
        "draft": asdict(draft),
        "ozon_import_payload": build_ozon_import_payload(draft),
    }
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.name = f"ozon_card_{draft.offer_id}.json"
    buf.seek(0)
    return buf


def export_ozon_card_xlsx(draft: OzonCardDraft) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Карточка Ozon"

    ws["A1"] = "Черновик карточки Ozon"
    ws["A1"].font = Font(size=16, bold=True, color="1F2937")
    ws["A2"] = f"Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    ws["A2"].font = Font(color="6B7280")
    ws.merge_cells("A1:C1")
    ws.merge_cells("A2:C2")

    rows = [
        ("Артикул", draft.offer_id, "Уникальный offer_id"),
        ("Название", draft.name, "Тип + бренд + ключевые свойства"),
        ("Категория", draft.category_hint or "", "Проверьте точную категорию Ozon"),
        ("Бренд", draft.brand, "Для неизвестного бренда обычно указывают 'Нет бренда'"),
        ("Цена", draft.price or "", "Цена продажи, RUB"),
        ("Старая цена", draft.old_price or "", "Можно очистить, если не нужна"),
        ("НДС", draft.vat, "0, 10, 20 или без НДС согласно кабинету"),
        ("Вес, г", draft.weight_g or "", "Обязательное поле для API"),
        ("Ширина, мм", draft.width_mm or "", "Обязательное поле для API"),
        ("Высота, мм", draft.height_mm or "", "Обязательное поле для API"),
        ("Глубина, мм", draft.depth_mm or "", "Обязательное поле для API"),
        ("Фото", "\n".join(draft.images), "URL изображений"),
        ("Ключевые слова", ", ".join(draft.keywords), "Для SEO и проверки полноты"),
        ("Оценка качества", build_ozon_card_quality_report(draft).score, "Оценка готовности карточки"),
        ("Замечания качества", "\n".join(build_ozon_card_quality_report(draft).warnings), "Что мешает публикации"),
        ("Чек-лист", "\n".join(draft.checklist), "Что проверить перед публикацией"),
        ("Конкуренты", draft.competitor_summary, "Краткий анализ выдачи маркетплейсов; подробности на отдельном листе"),
        ("AI-заметки", draft.ai_notes, "Пояснения и ограничения черновика"),
        ("Описание", draft.description, "Можно редактировать перед загрузкой"),
    ]

    try:
        ws.unmerge_cells("A1:C1")
        ws.unmerge_cells("A2:C2")
    except Exception:
        pass
    ws["A1"] = ""
    ws["A2"] = ""
    rows.insert(14, ("Преимущества", "\n".join(draft.selling_points), "Короткие буллиты с выгодами для покупателя"))

    start = 1
    headers = ["Поле", "Значение", "Комментарий"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(start, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")
        cell.alignment = Alignment(horizontal="center")

    for idx, row in enumerate(rows, start + 1):
        for col, value in enumerate(row, 1):
            cell = ws.cell(idx, col, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # Keep competitor offers and their image URLs as research references, not product assets.
    ws_comp = wb.create_sheet("Конкуренты")
    competitor_headers = [
        "Площадка",
        "Название конкурента",
        "Цена, ₽",
        "Старая цена, ₽",
        "Скидка, %",
        "Рейтинг",
        "Отзывы",
        "Наличие",
        "Продавец",
        "Ссылка на товар",
        "Фото конкурента (справочно)",
    ]
    for col, header in enumerate(competitor_headers, 1):
        cell = ws_comp.cell(1, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="475569")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for idx, item in enumerate(draft.competitors, 2):
        ws_comp.cell(idx, 1, item.get("marketplace") or "")
        ws_comp.cell(idx, 2, item.get("name") or "")
        ws_comp.cell(idx, 3, item.get("price") or "")
        ws_comp.cell(idx, 4, item.get("old_price") or "")
        ws_comp.cell(idx, 5, item.get("discount_pct") if item.get("discount_pct") is not None else "")
        ws_comp.cell(idx, 6, item.get("rating") if item.get("rating") is not None else "")
        ws_comp.cell(idx, 7, item.get("reviews_count") if item.get("reviews_count") is not None else "")
        ws_comp.cell(idx, 8, item.get("availability") or "не определено")
        ws_comp.cell(idx, 9, item.get("seller_name") or "")
        product_url = item.get("url") or ""
        image_url = item.get("image_url") or ""
        ws_comp.cell(idx, 10, product_url)
        ws_comp.cell(idx, 11, image_url)
        if product_url.startswith(("https://", "http://")):
            ws_comp.cell(idx, 10).hyperlink = product_url
            ws_comp.cell(idx, 10).style = "Hyperlink"
        if image_url.startswith(("https://", "http://")):
            ws_comp.cell(idx, 11).hyperlink = image_url
            ws_comp.cell(idx, 11).style = "Hyperlink"
        for col in range(1, 12):
            ws_comp.cell(idx, col).alignment = Alignment(vertical="top", wrap_text=True)
    ws_comp.freeze_panes = "A2"
    for col, width in {1: 18, 2: 52, 3: 14, 4: 14, 5: 12, 6: 12, 7: 12, 8: 18, 9: 24, 10: 65, 11: 65}.items():
        ws_comp.column_dimensions[get_column_letter(col)].width = width
    ws_comp["M1"] = (
        "Важно: фото на этом листе принадлежат карточкам конкурентов и приведены только для анализа. Не загружайте их как фотографии своего товара. Наличие может быть неизвестно, если площадка не отдала этот параметр."
    )
    ws_comp["M1"].alignment = Alignment(wrap_text=True, vertical="top")
    ws_comp.column_dimensions["M"].width = 55

    attr_start = start + len(rows) + 3
    ws.cell(attr_start, 1, "Характеристики").font = Font(size=14, bold=True)
    ws.cell(attr_start + 1, 1, "Название").font = Font(bold=True, color="FFFFFF")
    ws.cell(attr_start + 1, 2, "Значение").font = Font(bold=True, color="FFFFFF")
    ws.cell(attr_start + 1, 1).fill = PatternFill("solid", fgColor="059669")
    ws.cell(attr_start + 1, 2).fill = PatternFill("solid", fgColor="059669")

    for row_idx, (key, value) in enumerate(sorted(draft.attributes.items()), attr_start + 2):
        ws.cell(row_idx, 1, key)
        ws.cell(row_idx, 2, value)

    widths = {1: 22, 2: 64, 3: 44}
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.name = f"ozon_card_{draft.offer_id}.xlsx"
    buf.seek(0)
    return buf


def export_ozon_cards_batch_json(items: list[OzonCardBatchItem]) -> io.BytesIO:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": _build_batch_counts(items),
        "items": [
            {
                "source": item.source,
                "status": item.status,
                "message": item.message,
                "draft": asdict(item.draft) if item.draft else None,
                "ozon_import_payload": build_ozon_import_payload(item.draft) if item.draft else None,
            }
            for item in items
        ],
    }
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.name = f"ozon_cards_batch_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    buf.seek(0)
    return buf


def export_ozon_cards_batch_xlsx(items: list[OzonCardBatchItem]) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Сводка"
    ws_cards = wb.create_sheet("Карточки")
    ws_attrs = wb.create_sheet("Характеристики")
    ws_competitors = wb.create_sheet("Конкуренты")

    counts = _build_batch_counts(items)
    ws_summary["A1"] = "Пакет карточек Ozon"
    ws_summary["A1"].font = Font(size=16, bold=True, color="1F2937")
    ws_summary["A2"] = f"Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    ws_summary["A3"] = (
        f"Всего: {counts['total']} | готово к проверке: {counts['ready']} | нужна доработка: {counts['needs_review']} | ошибки: {counts['error']}"
    )
    ws_summary["A5"] = "Как работать с файлом"
    ws_summary["A5"].font = Font(bold=True)
    ws_summary["A6"] = "1. Начните с листа «Карточки» и отфильтруйте статус «Нужна доработка»."
    ws_summary["A7"] = "2. Заполните пропуски: категорию, фото, вес и габариты."
    ws_summary["A8"] = "3. Лист «Характеристики» используйте как подсказку для обязательных полей Ozon."
    ws_summary["A9"] = (
        "4. Лист «Конкуренты» содержит реальные ссылки и цены найденных предложений; фото конкурентов — только для анализа."
    )

    for col, width in {1: 28, 2: 28, 3: 80}.items():
        ws_summary.column_dimensions[get_column_letter(col)].width = width

    card_headers = [
        "№",
        "Статус",
        "Что проверить",
        "Артикул",
        "Название",
        "Категория",
        "Бренд",
        "Цена",
        "Старая цена",
        "НДС",
        "Вес, г",
        "Ширина, мм",
        "Высота, мм",
        "Глубина, мм",
        "Фото",
        "Ключевые слова",
        "Описание",
        "Конкуренты",
        "AI-заметки",
        "Источник",
        "Ошибка",
    ]
    _write_header_row(ws_cards, card_headers)
    for idx, item in enumerate(items, 1):
        draft = item.draft
        missing = _draft_missing_fields(draft) if draft else []
        row = [
            idx,
            _human_batch_status(item.status),
            ", ".join(missing) if missing else "",
            draft.offer_id if draft else "",
            draft.name if draft else "",
            draft.category_hint if draft else "",
            draft.brand if draft else "",
            draft.price if draft else "",
            draft.old_price if draft else "",
            draft.vat if draft else "",
            draft.weight_g if draft else "",
            draft.width_mm if draft else "",
            draft.height_mm if draft else "",
            draft.depth_mm if draft else "",
            "\n".join(draft.images) if draft else "",
            ", ".join(draft.keywords) if draft else "",
            draft.description if draft else "",
            draft.competitor_summary if draft else "",
            draft.ai_notes if draft else "",
            item.source,
            item.message,
        ]
        ws_cards.append(row)

    attr_headers = ["№", "Артикул", "Название", "Характеристика", "Значение"]
    _write_header_row(ws_attrs, attr_headers)
    for idx, item in enumerate(items, 1):
        if not item.draft:
            continue
        for key, value in sorted(item.draft.attributes.items()):
            ws_attrs.append([idx, item.draft.offer_id, item.draft.name, key, value])

    competitor_headers = [
        "№ карточки",
        "Артикул",
        "Площадка",
        "Название конкурента",
        "Цена, ₽",
        "Старая цена, ₽",
        "Скидка, %",
        "Рейтинг",
        "Отзывы",
        "Наличие",
        "Продавец",
        "Ссылка на товар",
        "Фото конкурента (справочно)",
    ]
    _write_header_row(ws_competitors, competitor_headers)
    for card_idx, item in enumerate(items, 1):
        if not item.draft:
            continue
        for competitor in item.draft.competitors:
            ws_competitors.append(
                [
                    card_idx,
                    item.draft.offer_id,
                    competitor.get("marketplace") or "unknown",
                    competitor.get("name") or "",
                    competitor.get("price") or "",
                    competitor.get("old_price") or "",
                    competitor.get("discount_pct") if competitor.get("discount_pct") is not None else "",
                    competitor.get("rating") if competitor.get("rating") is not None else "",
                    competitor.get("reviews_count") if competitor.get("reviews_count") is not None else "",
                    competitor.get("availability") or "unknown",
                    competitor.get("seller_name") or "",
                    competitor.get("url") or "",
                    competitor.get("image_url") or "",
                ]
            )
            row_idx = ws_competitors.max_row
            for col, key in ((12, "url"), (13, "image_url")):
                link = competitor.get(key) or ""
                if link.startswith(("https://", "http://")):
                    ws_competitors.cell(row_idx, col).hyperlink = link
                    ws_competitors.cell(row_idx, col).style = "Hyperlink"
    for col, width in {
        1: 12,
        2: 24,
        3: 18,
        4: 52,
        5: 14,
        6: 14,
        7: 12,
        8: 12,
        9: 12,
        10: 18,
        11: 24,
        12: 65,
        13: 65,
    }.items():
        ws_competitors.column_dimensions[get_column_letter(col)].width = width
    _style_batch_sheet(ws_cards)
    _style_batch_sheet(ws_attrs)
    _style_batch_sheet(ws_competitors)

    buf = io.BytesIO()
    wb.save(buf)
    buf.name = f"ozon_cards_batch_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    buf.seek(0)
    return buf


def format_ozon_card_preview(draft: OzonCardDraft) -> str:
    quality = build_ozon_card_quality_report(draft)
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

    missing_text = ", ".join(missing) if missing else "критичных пропусков нет"
    readiness = "можно проверять и дорабатывать" if not missing else "нужна ручная доработка перед загрузкой"
    competitor_text = html.escape(draft.competitor_summary) if draft.competitor_summary else "данные не получены"
    next_steps = (
        "Что делать дальше:\n"
        "1. Откройте XLSX и заполните/проверьте пункты из строки «Что проверить».\n"
        "2. Сверьте категорию и обязательные атрибуты в кабинете Ozon Seller.\n"
        "3. После правок используйте XLSX как черновик для ручного импорта. JSON пока нужен как техфайл для будущей отправки через Seller API."
    )
    return (
        "<b>Черновик карточки Ozon готов</b>\n\n"
        f"<b>Название:</b> {html.escape(draft.name)}\n"
        f"<b>Категория:</b> {html.escape(draft.category_hint or 'нужно уточнить')}\n"
        f"<b>Артикул:</b> <code>{html.escape(draft.offer_id)}</code>\n"
        f"<b>Цена:</b> {draft.price or 'не указана'} ₽\n"
        f"<b>Бренд:</b> {html.escape(draft.brand)}\n"
        f"<b>AI:</b> {html.escape(draft.ai_notes or 'Статус не определён')}\n"
        f"<b>Оценка качества данных (готовность):</b> {quality.score}/100\n"
        f"<b>Характеристик:</b> {len(draft.attributes)}\n"
        f"<b>Фото:</b> {len(draft.images)}\n"
        f"<b>Анализ конкурентов:</b> {competitor_text}\n"
        f"<b>Статус:</b> {readiness}\n"
        f"<b>Что проверить:</b> {missing_text}\n\n"
        f"{next_steps}"
    )


def format_ozon_batch_preview(items: list[OzonCardBatchItem]) -> str:
    counts = _build_batch_counts(items)
    problem_lines = []
    for idx, item in enumerate(items, 1):
        if item.status == "error":
            problem_lines.append(f"{idx}. ошибка: {html.escape(str(item.message)[:80])}")
            continue
        missing = _draft_missing_fields(item.draft)
        if missing:
            name = html.escape(str(item.draft.name if item.draft else item.source)[:60])
            problem_lines.append(f"{idx}. {name}: {', '.join(missing)}")

    problems_text = "\n".join(problem_lines[:10]) if problem_lines else "критичных пропусков нет"
    if len(problem_lines) > 10:
        problems_text += f"\n...и ещё {len(problem_lines) - 10}"

    return (
        "<b>Пакет карточек Ozon готов</b>\n\n"
        f"<b>Всего:</b> {counts['total']}\n"
        f"<b>Можно проверять:</b> {counts['ready']}\n"
        f"<b>Нужна доработка:</b> {counts['needs_review']}\n"
        f"<b>Ошибки:</b> {counts['error']}\n\n"
        f"<b>Что требует внимания:</b>\n{problems_text}\n\n"
        "Что дальше: откройте общий XLSX, начните с листа «Сводка», затем на листе «Карточки» "
        "отфильтруйте «Нужна доработка». JSON прикладываю как технический файл под будущую API-загрузку."
    )


def _build_title(text: str, brand: str, category: str | None) -> str:
    """Build SEO-optimized title in format: Тип + Бренд + Ключевые свойства.

    Ozon title best practices:
    - Start with product type (книга, кабель, капсулы)
    - Include brand if known
    - Add key differentiators (объём, цвет, материал, размер)
    - Keep under 140 chars
    - No marketing fluff (лучший, купить, недорого)
    """
    explicit = _normalize_b6_notation(_extract_value(text, ["название", "товар", "name"]) or "")
    if explicit:
        cleaned = _strip_commercial_terms(explicit)
        # If explicit title has 3+ words, use it (append brand if missing)
        if len(cleaned.split()) >= 3:
            if brand and brand != "Нет бренда" and brand.lower() not in cleaned.lower():
                cleaned = f"{cleaned} {brand}"
            return cleaned[:140]
        # Preserve an explicit two-word product name (e.g. "Беспроводные наушники")
        # instead of replacing it with a type guessed from substrings in "беспроводные".
        if len(cleaned.split()) == 2:
            parts = [cleaned]
            for feature in _extract_key_features(text):
                if feature.lower() not in cleaned.lower():
                    parts.append(feature)
            if brand and brand != "Нет бренда" and brand.lower() not in cleaned.lower():
                parts.append(brand)
            return " ".join(parts)[:140]
        # A one-word explicit title needs a product type and verified features.
        product_type = _guess_product_type(text, category) or cleaned
        features = _extract_key_features(text)
        parts = [product_type, *features]
        if brand and brand != "Нет бренда" and brand.lower() not in " ".join(parts).lower():
            parts.append(brand)
        title = " ".join(parts).strip()
        if title:
            return title[:140]

    # Extract product type from category or text
    product_type = _guess_product_type(text, category)

    # Extract key features (volume, color, material, size, count)
    features = _extract_key_features(text)

    # Build structured title: Type + Features + Brand
    parts = []
    if product_type:
        parts.append(product_type)
    if features:
        parts.extend(features)
    if brand and brand != "Нет бренда" and brand.lower() not in " ".join(parts).lower():
        parts.append(brand)

    title = " ".join(parts).strip()
    if not title:
        # Fallback: extract first meaningful line
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
        first_line = re.sub(r"https?://\S+", "", first_line)
        first_line = re.sub(r"\b(цена|стоимость|бренд|категория)\s*[:=-].*", "", first_line, flags=re.I)
        first_line = _normalize_b6_notation(first_line)
        first_line = _strip_commercial_terms(first_line)
        words = [w for w in re.split(r"\s+", first_line) if len(w) > 1]
        title = " ".join(words[:16]).strip(" ,.;:-")

    if not title and category:
        title = category
    # Always append brand if not already present
    if brand and brand != "Нет бренда" and brand.lower() not in title.lower():
        title = f"{title} {brand}"
    return title[:140] or "Новый товар"


def _guess_product_type(text: str, category: str | None) -> str:
    """Guess product type from text and category."""
    low = (text + " " + (category or "")).lower()
    type_map = [
        # Books
        (r"(книга|книж|роман|учебник|собрание сочинени)", "Книга"),
        # Supplements
        (r"(капсул|таблет|добавк|бад|витамин|минерал|магни|кальций|цинк|железо)", "БАД"),
        # Electronics
        (r"(кабел\w*|(?<!без)провод\w*|шнур\w*)", "Кабель"),
        (r"(наушник|гарнитур)", "Наушники"),
        (r"(чехол|защитн)", "Чехол"),
        (r"(держател|креплен)", "Держатель"),
        (r"(зарядн|адаптер|блок питания)", "Зарядное устройство"),
        # Home
        (r"(коврик|килим)", "Коврик"),
        (r"(кресл|стул)", "Кресло"),
        (r"(лампа|светильник)", "Лампа"),
        # Clothing
        (r"(футбол|рубашк|блуз)", "Футболка"),
        (r"(джинс|брюки|штаны)", "Джинсы"),
        (r"(курт|плащ|пальто)", "Куртка"),
        # Food
        (r"(чай|кофе|сок|вода)", "Напиток"),
        (r"(шоколад|конфет|печенье|бисквит)", "Сладость"),
    ]
    for pattern, ptype in type_map:
        if re.search(pattern, low):
            return ptype
    return ""


def _extract_key_features(text: str) -> list[str]:
    """Extract key product features: volume, count, color, material, size, connectors."""
    features = []
    low = text.lower()

    # Connector types (for electronics)
    connector_match = re.search(
        r"(usb[- ]?[a-c]|lightning|type[- ]?c|micro[- ]?usb|hdmi|displayport|jack|3\.5|6\.3)", low
    )
    if connector_match:
        features.append(connector_match.group(1).upper().replace(" ", "-"))

    # Volume/weight
    vol_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(мл|л|g|кг|мг|мкг)", low)
    if vol_match:
        features.append(f"{vol_match.group(1)}{vol_match.group(2)}")

    # Count
    count_match = re.search(r"(\d+)\s*(шт|капсул|таблет|т|лист|страниц)", low)
    if count_match:
        features.append(f"{count_match.group(1)}{count_match.group(2)}")

    # Color
    color_match = re.search(r"(цвет|color)\s*[:=-]\s*(\S+)", low)
    if color_match:
        features.append(color_match.group(2).title())

    # Material
    mat_match = re.search(r"(материал|material)\s*[:=-]\s*(\S+)", low)
    if mat_match:
        features.append(mat_match.group(2).title())

    # Size/dimensions
    size_match = re.search(r"(\d+)\s*[xх]\s*(\d+)", low)
    if size_match:
        features.append(f"{size_match.group(1)}x{size_match.group(2)}")

    # Language (for books)
    lang_match = re.search(r"(язык|language)\s*[:=-]\s*(\S+)", low)
    if lang_match:
        features.append(lang_match.group(2).title())

    # Pages (for books)
    pages_match = re.search(r"(\d+)\s*(страниц|стр|с)", low)
    if pages_match:
        features.append(f"{pages_match.group(1)}{pages_match.group(2)}")

    return features[:4]  # Max 4 features to keep title readable


def _build_description(
    text: str,
    title: str,
    *,
    brand: str,
    category: str | None,
    attributes: dict[str, str],
    selling_points: list[str],
) -> str:
    explicit = _extract_value(text, ["описание", "description"])
    if explicit:
        base = _remove_service_noise(_normalize_b6_notation(explicit))
        if len(base) < 80:
            base = _build_marketing_description(
                title, brand=brand, category=category, attributes=attributes, selling_points=selling_points
            )
        return _remove_service_noise(base)[:4000]
    else:
        base = _build_marketing_description(
            title, brand=brand, category=category, attributes=attributes, selling_points=selling_points
        )

    if len(base) < 80:
        base = _build_marketing_description(
            title, brand=brand, category=category, attributes=attributes, selling_points=selling_points
        )
    return base[:4000]


def _build_marketing_description(
    title: str,
    *,
    brand: str,
    category: str | None,
    attributes: dict[str, str],
    selling_points: list[str],
) -> str:
    """Build buyer-focused marketing description.

    Structure:
    1. Hook — what the product is and who it's for
    2. Key benefits — 3-4 specific advantages
    3. Specifications — important product facts
    4. Call to action — check details before purchase
    """
    product = title.strip() or "Товар"
    brand_part = "" if not brand or brand == "Нет бренда" or brand.lower() in product.lower() else f" {brand}"
    category_low = (category or "").lower()

    # Detect product category for tailored content
    is_supplement = any(
        t in category_low or t in product.lower() for t in ("витамин", "бад", "магни", "капсул", "таблет")
    )
    is_book = any(t in category_low or t in product.lower() for t in ("книга", "книж", "roman", "учебник"))
    is_electronics = any(
        t in category_low or t in product.lower() for t in ("кабел", "наушник", "зарядн", "чехол", "держател")
    )
    is_clothing = any(
        t in category_low or t in product.lower() for t in ("футбол", "рубашк", "джинс", "курт", "штан", "брюк")
    )
    is_food = any(
        t in category_low or t in product.lower() for t in ("чай", "кофе", "сок", "шоколад", "конфет", "печенье")
    )
    is_home = any(t in category_low or t in product.lower() for t in ("коврик", "кресл", "лампа", "мебел", "йог"))
    is_sports = any(t in category_low or t in product.lower() for t in ("спорт", "фитнес", "йог", "тренаж", "мяч"))

    # Build lead paragraph — product identity + target audience
    if is_supplement:
        lead = (
            f"{product}{brand_part} — товар из категории витаминов и минеральных комплексов. "
            "Перед покупкой сверьте полный состав, дозировку, форму выпуска и количество единиц "
            "с информацией на упаковке: эти характеристики должны быть подтверждены продавцом."
        )
    elif is_book:
        lead = (
            f"{product}{brand_part} — издание для читателей, которые ищут практическую информацию "
            "или качественный контент. Удобный формат, понятная подача, актуальное содержание."
        )
    elif is_electronics:
        lead = (
            f"{product}{brand_part} — аксессуар для тех, кто ценит совместимость и надёжность. "
            "Подходит для повседневного использования с основными устройствами."
        )
    elif is_clothing:
        lead = (
            f"{product}{brand_part} — предмет одежды с вниманием к деталям: материал, крой и посадка "
            "продуманы для комфортной носки. Подходит для повседневного использования."
        )
    elif is_food:
        lead = (
            f"{product}{brand_part} — продукт с вниманием к составу и вкусу. "
            "Подходит для тех, кто ценит качество и натуральные ингредиенты."
        )
    elif is_home:
        lead = (
            f"{product}{brand_part} — товар для дома с продуманным дизайном и практичным применением. "
            "Подходит для повседневного использования."
        )
    elif is_sports:
        lead = (
            f"{product}{brand_part} — спортивный товар, рассчитанный на комфорт и функциональность. "
            "Подходит для регулярных тренировок и активного отдыха."
        )
    else:
        lead = (
            f"{product}{brand_part} — практичный товар с продуманным дизайном и понятным применением. "
            "Подходит для повседневного использования."
        )

    # Build benefits section — use actual selling_points, not generic templates
    benefits = []
    if selling_points:
        benefits.extend(selling_points[:4])
    if not benefits:
        benefits = [
            "Характеристики указаны прямо в карточке — сравнивайте перед покупкой",
            "Фото показывают реальный товар — оцените дизайн и качество",
            "Проверьте комплектацию и габариты перед заказом",
        ]

    # Build specs section — facts from attributes
    specs = []
    important_keys = [
        "Объём",
        "Вес",
        "Размер",
        "Цвет",
        "Материал",
        "Язык",
        "Страниц",
        "Количество",
        "Форма",
        "Дозировка",
        "Состав",
        "Комплектация",
        "Тип разъёма",
        "Длина",
        "Мощность",
        "Плотность",
    ]
    for key in important_keys:
        val = attributes.get(key)
        if val and val != "нужно заполнить":
            specs.append(f"• {key}: {val}")

    # Build closing — product-type-specific
    if is_supplement:
        closing = (
            "Перед покупкой проверьте состав, рекомендации по применению и противопоказания. "
            "Информация предоставлена производителем."
        )
    elif is_book:
        closing = "Перед покупкой убедитесь, что формат и язык издания соответствуют вашим ожиданиям."
    elif is_electronics:
        closing = "Проверьте совместимость разъёмов и тип подключения с вашими устройствами перед покупкой."
    elif is_clothing:
        closing = "Перед покупкой сверьте размерную сетку и уточните состав ткани."
    elif is_food:
        closing = "Перед покупкой проверьте срок годности, состав и условия хранения."
    elif is_home:
        closing = "Проверьте габариты упаковки и совместимость с вашим интерьером перед покупкой."
    elif is_sports:
        closing = "Перед покупкой убедитесь, что размер и характеристики подходят для ваших задач."
    else:
        closing = "Проверьте комплектацию, габариты и совместимость перед покупкой."

    # Assemble description
    parts = [lead]

    if benefits:
        parts.append("Преимущества:\n" + "\n".join(f"✓ {b}" for b in benefits))

    if specs:
        parts.append("Характеристики:\n" + "\n".join(specs))

    # Add source facts if available (preserve "Из источника:" section)
    facts = []
    for key in ("Рейтинг", "Отзывов", "Наличие"):
        value = attributes.get(key)
        if value:
            facts.append(f"{key}: {value}")
    if facts:
        parts.append("Из источника:\n" + "\n".join(f"• {f}" for f in facts))

    parts.append(closing)

    return "\n\n".join(parts)[:4000]


def _normalize_b6_notation(text: str) -> str:
    value = text or ""
    value = re.sub(r"\b(?:v|ви|в)\s*6\b", "B6", value, flags=re.I)
    value = re.sub(r"\b(?:витамин\s+)?в\s*6\b", "B6", value, flags=re.I)
    value = re.sub(r"\bmag\s*6\b", "B6", value, flags=re.I)
    return value


def _collapse_description(text: str) -> str:
    value = _clean(text)
    value = re.sub(r"\s+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def _normalize_category_hint(category: str | None, title: str) -> str | None:
    if not category:
        return category
    low = category.lower()
    title_low = title.lower()
    if "витамин" in low and any(token in title_low for token in ("магни", "magnesium", "магнез")):
        return "Красота и здоровье/Витамины и БАДы/Минералы"
    return category


def _extract_attributes(text: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for line in text.splitlines():
        if re.search(r"https?://", line, flags=re.I):
            continue
        match = re.match(r"\s*([A-Za-zА-Яа-яЁё0-9 /_-]{3,40})\s*[:=-]\s*(.{2,120})\s*$", line)
        if not match:
            continue
        key = match.group(1).strip().capitalize()
        value = match.group(2).strip()
        if key.lower() in {
            "цена",
            "стоимость",
            "название",
            "товар",
            "описание",
            "бренд",
            "категория",
            "задача",
            "источник",
            "старая цена",
        }:
            continue
        attributes[key] = value

    color = _extract_value(text, ["цвет"])
    if color:
        attributes.setdefault("Цвет", color)
    material = _extract_value(text, ["материал"])
    if material:
        attributes.setdefault("Материал", material)
    package = _extract_value(text, ["комплектация"])
    if package:
        attributes.setdefault("Комплектация", package)
    return attributes


def _build_keywords(title: str, category: str | None, attributes: dict[str, str], brand: str) -> list[str]:
    source = " ".join([title, category or "", " ".join(attributes.values())])
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9+_-]{3,}", source.lower())
    cleaned = _sanitize_keywords(words, brand=brand, limit=30)
    whitelist_roots = _category_keyword_whitelist(category)
    if whitelist_roots:
        scoped = [w for w in cleaned if any(root in w for root in whitelist_roots)]
        if scoped:
            return scoped[:20]
    return cleaned[:20]


def _extract_value(text: str, keys: list[str]) -> str | None:
    for key in keys:
        match = re.search(rf"(?:^|\n)\s*{re.escape(key)}\s*[:=-]\s*(.+)", text, flags=re.I)
        if match:
            return match.group(1).strip()[:300]
    return None


def _extract_price(text: str) -> int | None:
    patterns = [
        r"(?:цена|стоимость)\s*[:=-]?\s*([\d\s]{2,8})(?:₽|руб|р)?",
        r"(?:за|по)\s*([\d\s]{2,8})(?:₽|руб|р)?",
        r"([\d\s]{2,8})\s*(?:₽|руб|р)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = int(re.sub(r"\D", "", match.group(1)) or "0")
            if 1 <= value <= 50_000_000:
                return value
    return None


def _extract_old_price(text: str, price: int | None = None) -> int | None:
    patterns = [
        r"(?:старая цена|old_price|old price)\s*[:=-]?\s*([\d\s]{2,8})(?:₽|руб|р)?",
        r"(?:до скидки|было)\s*[:=-]?\s*([\d\s]{2,8})(?:₽|руб|р)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = int(re.sub(r"\D", "", match.group(1)) or "0")
        if 1 <= value <= 50_000_000 and (price is None or value > price):
            return value
    return None


def _strip_commercial_terms(text: str) -> str:
    text = re.sub(r"\b(?:цена|стоимость)\s*[:=-]?\s*[\d\s]{1,8}\s*(?:₽|руб\.?|р\.?)?", " ", text, flags=re.I)
    text = re.sub(r"\b(?:за|по)\s*[\d\s]{2,8}\s*(?:₽|руб\.?|р\.?)?", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,.;:-")


def _extract_dimensions(text: str) -> dict[str, int]:
    match = re.search(r"(\d{1,4})\s*[xх*]\s*(\d{1,4})\s*[xх*]\s*(\d{1,4})\s*(мм|см|mм)?", text, flags=re.I)
    if not match:
        return {}
    values = [int(match.group(i)) for i in range(1, 4)]
    unit = (match.group(4) or "мм").lower()
    if unit == "см":
        values = [v * 10 for v in values]
    return {"width_mm": values[0], "height_mm": values[1], "depth_mm": values[2]}


def _extract_weight(text: str) -> int | None:
    match = re.search(r"(?:вес|weight)\s*[:=-]?\s*(\d{1,6})\s*(кг|kg|г|g)?", text, flags=re.I)
    if not match:
        return None
    value = int(match.group(1))
    unit = (match.group(2) or "г").lower()
    if unit in {"кг", "kg"}:
        value *= 1000
    return value


def _extract_urls(text: str) -> list[str]:
    return [url.rstrip(".,);]}>") for url in re.findall(r"https?://\S+", text or "", flags=re.I)]


def _looks_like_image(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _guess_category(text: str) -> str | None:
    low = text.lower()
    rules = [
        ("держател", "Автомобильные держатели"),
        ("наушник", "Наушники и гарнитуры"),
        ("кабель", "Кабели"),
        ("чехол", "Чехлы"),
        ("заряд", "Зарядные устройства"),
        ("подписка", "Цифровые товары"),
        ("магни", "Красота и здоровье/Витамины и БАДы/Минералы"),
        ("витамин", "Красота и здоровье/Витамины и БАДы/Витамины"),
        ("бад", "Красота и здоровье/Витамины и БАДы"),
        ("капсул", "Красота и здоровье/Витамины и БАДы"),
        ("таблет", "Красота и здоровье/Витамины и БАДы"),
    ]
    for needle, category in rules:
        if needle in low:
            return _map_to_ozon_category_path(category)
    wb_category = _extract_value(text, ["категория wb", "wb category", "категория"])
    if wb_category:
        return _map_to_ozon_category_path(wb_category)
    return None


def _specialize_category_path(text: str, title: str, category: str | None) -> str | None:
    low = f"{text} {title} {category or ''}".lower()
    if any(token in low for token in ("магни", "magnesium", "магнез")) and category and "витамин" in category.lower():
        return "Красота и здоровье/Витамины и БАДы/Минералы"
    return category


def _build_offer_id(title: str) -> str:
    translit = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ы": "y",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    raw = "".join(translit.get(ch, ch) for ch in title.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:32] or "product"
    digest = hashlib.md5(title.encode("utf-8")).hexdigest()[:6]
    return f"{slug}-{digest}"[:50]


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "").strip()


AI_CARD_SYSTEM_PROMPT = """Ты эксперт по созданию карточек товаров для маркетплейсов Ozon и Wildberries.

Твоя задача — улучшить черновик карточки, сделав его привлекательным для покупателя и соответствующим требованиям маркетплейса.

ПРАВИЛА:
1. Не выдумывай факты — используй только данные из исходного текста
2. Пиши на русском языке, грамотно и по делу
3. Формула названия: Тип товара (книга, кабель, капсулы) + Бренд + Модель (если модель есть в исходнике/attributes — не выдумывай её) + ключевое свойство. Если бренда/модели нет — просто пропусти эту часть, не пиши "Нет бренда" в название
4. Описание должно отвечать на вопрос "зачем мне это покупать?" — конкретные выгоды, не общие слова
5. Ключевые слова — реальные поисковые запросы покупателей (в т.ч. из competitor_seo_gap, если релевантны), без переспама: каждое слово по делу, не повторяй одну и ту же характеристику разными словами ради количества
6. Продажные пункты — конкретные, не "удобен для ежедневного использования"
7. Без медицинских, юридических, гарантийных обещаний
8. Без абсолютов ("лучший", "единственный", "идеальный")
9. Без слов "скидка", "акция", "купить недорого" — это запрещено на маркетплейсах
10. Конкурентная карточка — не та, что прямо сравнивает себя с другими ("дешевле, чем у конкурентов" тоже запрещено), а та, что явно и конкретно закрывает вопросы покупателя раньше, чем он откроет соседнюю карточку: используй competitor_seo_gap для keywords/атрибутов, если слово реально относится к этому товару, и выноси в selling_points самые конкретные факты из исходника (состав, размер, материал, применение) — это и есть отстройка от конкурентов, а не общие фразы
11. Для витаминов и БАДов особенно строго: не утверждай, что товар подходит для ежедневного/регулярного приёма, содержит определённую дозу или порцию, поставляется напрямую от производителя, имеет конкретную форму/количество капсул или даёт эффект, если этого нет в source_text. Не добавляй шаблонные обещания о здоровье. Если данных нет — прямо укажи, что состав, дозировку и форму выпуска нужно сверить на упаковке.

ФОРМАТ ОТВЕТА — только валидный JSON без markdown-обёртки."""


def _sanitize_supplement_draft(draft: OzonCardDraft) -> None:
    """Apply factual-claim filtering to supplement drafts, including AI-off/error fallbacks."""
    if not _is_supplement_draft(draft):
        return
    draft.description = _remove_unverified_supplement_claims(draft.description, draft.source_text)
    draft.selling_points = [
        cleaned
        for point in draft.selling_points
        if (cleaned := _remove_unverified_supplement_claims(point, draft.source_text))
    ]
    if not draft.description:
        draft.description = _build_marketing_description(
            draft.name,
            brand=draft.brand,
            category=draft.category_hint,
            attributes=draft.attributes,
            selling_points=draft.selling_points,
        )


def _is_supplement_draft(draft: OzonCardDraft) -> bool:
    marker = f"{draft.name} {draft.category_hint or ''}".lower()
    return any(token in marker for token in ("витамин", "бад", "магни", "капсул", "таблет", "минерал"))


def _remove_unverified_supplement_claims(text: str, source_text: str) -> str:
    """Drop common supplement claims unless the source explicitly supports them."""
    source = (source_text or "").lower()
    claims = [
        r"[^.!?]*(?:напрямую|непосредственно|прямо)\s+от\s+производител[яь][^.!?]*[.!?]?",
        r"[^.!?]*поставля[ею]тся\s+от\s+производител[яь][^.!?]*[.!?]?",
        r"[^.!?]*информаци[яи]\s+предоставлен[ао]?\s+производител[емя][^.!?]*[.!?]?",
        r"[^.!?]*(?:рассчитан[ао]?\s+на\s+курс|курс\s+при[её]ма|не\s+нужно\s+пересчитывать\s+доз[уы])[^.!?]*[.!?]?",
        r"[^.!?]*(?:указан[аоы]?\s+прямо\s+в\s+карточке|вся\s+ключевая\s+информаци[яи]\s+в\s+одном\s+месте)[^.!?]*[.!?]?",
        r"[^.!?]*(?:преимущества|рекомендаци[яи]\s+по\s+применению)[^.!?]*[.!?]?",
    ]
    if not re.search(r"\b(?:ежедневн|регулярн)\w*", source):
        claims.append(r"[^.!?]*(?:ежедневн|регулярн)\w*[^.!?]*[.!?]?")
    if not re.search(r"\bпорци\w*", source):
        claims.append(r"[^.!?]*в\s+одной\s+порци\w*[^.!?]*[.!?]?")
    if not re.search(r"\b(?:капсул\w*|таблет\w*|порош\w*|жидк\w*)", source):
        claims.append(r"[^.!?]*(?:удобн\w*\s+формат|удобно\s+принимать)[^.!?]*[.!?]?")
    value = text or ""
    for pattern in claims:
        value = re.sub(pattern, " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" ;,.-")
    return value


def _build_ai_card_prompt(draft: OzonCardDraft, competitors: list[dict], profile: dict | None = None) -> str:
    profile = profile or {}
    existing_keywords = {kw.lower() for kw in draft.keywords}
    seo_gap = [word for word, _ in _top_competitor_words(competitors) if word not in existing_keywords][:10]
    payload = {
        "source_text": draft.source_text,
        "draft": asdict(draft),
        "profile": {
            "language": profile.get("language", "ru"),
            "tone_voice": profile.get("tone_voice", "professional"),
            "max_length": profile.get("max_length", 1500),
            "forbidden_words": profile.get("forbidden_words", []),
        },
        "competitors": _compact_competitors(competitors),
        "competitor_summary": draft.competitor_summary,
        "competitor_seo_gap": seo_gap,
        "required_json_schema": {
            "name": "SEO-название до 140 символов",
            "description": "продающее описание 700-1500 символов",
            "category_hint": "предполагаемая категория",
            "brand": "бренд или Нет бренда",
            "attributes": {"Название характеристики": "Значение"},
            "keywords": ["ключевые слова без повторов"],
            "selling_points": ["3-4 коротких буллита с выгодами для покупателя"],
            "checklist": ["что проверить или добавить перед публикацией"],
            "notes": "коротко: что улучшено и какие есть ограничения",
        },
    }
    return (
        "Улучши карточку товара для маркетплейса. "
        "Сохрани фактические данные из исходника. Конкурентов (уже отфильтрованы по релевантности товару) используй только "
        "для SEO-слов, ценового ориентира и чек-листа, не копируй чужие названия дословно и не выдумывай свойства товара. "
        "competitor_seo_gap — частые слова из релевантных карточек конкурентов, которых пока нет в keywords: включи те из них, "
        "что действительно описывают этот товар, остальные игнорируй. "
        "Если данных не хватает, вынеси это в checklist.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception as e:
        logger.warning(f"AI card JSON parse failed: {e}")
        return None
    return data if isinstance(data, dict) else None


def _clean_ai_string(value, *, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = _clean(value)
    return value[:max_len] if value else None


def _clean_string_list(value, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        item = _clean(item)
        marker = item.lower()
        if item and marker not in seen:
            result.append(item[:160])
            seen.add(marker)
        if len(result) >= limit:
            break
    return result


def _clean_string_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        key = _clean(key).capitalize()[:80]
        item = _clean(item)[:300]
        if key and item:
            result[key] = item
    return result


def _shorten(text: str, limit: int) -> str:
    return _clean(text)[:limit]


def _has_usable_ai_card_data(data: dict) -> bool:
    """Return True only when the model supplied at least one actual card field."""
    for key in ("name", "description", "category_hint"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return True
    attributes = data.get("attributes")
    if isinstance(attributes, dict) and any(
        isinstance(name, str) and name.strip() and isinstance(item, str) and item.strip()
        for name, item in attributes.items()
    ):
        return True
    for key in ("keywords", "selling_points"):
        value = data.get(key)
        if isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value):
            return True
    return False


def apply_card_profile(draft: OzonCardDraft, profile: dict | None) -> OzonCardDraft:
    profile = profile or {}
    forbidden = [str(x).strip().lower() for x in profile.get("forbidden_words", []) if str(x).strip()]
    if forbidden:
        draft.name = _remove_forbidden_words(draft.name, forbidden)
        draft.description = _remove_forbidden_words(draft.description, forbidden)
        draft.keywords = [k for k in draft.keywords if k.lower() not in forbidden]
        draft.selling_points = [_remove_forbidden_words(point, forbidden) for point in draft.selling_points]
        draft.selling_points = [x for x in draft.selling_points if x]

    max_len = int(profile.get("max_length") or 1500)
    if max_len > 0:
        draft.description = draft.description[:max_len]

    for attr in profile.get("required_attributes", []) or []:
        name = str(attr).strip()
        if not name or name in {"Бренд", "Категория"}:
            continue
        draft.attributes.setdefault(name, "нужно заполнить")

    return draft


def _remove_forbidden_words(text: str, forbidden: list[str]) -> str:
    value = text or ""
    for word in forbidden:
        if not word:
            continue
        value = re.sub(rf"\b{re.escape(word)}\b", " ", value, flags=re.I)
    value = re.sub(r"\s{2,}", " ", value).strip(" ,.;:-")
    return value


def _build_checklist(price: int | None, urls: list[str], weight: int | None, dimensions: dict[str, int]) -> list[str]:
    """Build comprehensive pre-publish checklist.

    Checklist should guide the seller through everything needed for a complete,
    attractive, and compliant Ozon listing.
    """
    checklist = []

    # Critical missing fields (card won't publish without these)
    if not price:
        checklist.append("❗ Указать цену продажи — карточка не опубликуется без цены")

    if not any(_looks_like_image(url) for url in urls):
        checklist.append("📷 Добавить фото: главное на белом фоне + 2-3 доп. ракурса")

    if not weight:
        checklist.append("⚖️ Указать вес в граммах — влияет на стоимость доставки")

    if not (dimensions.get("width_mm") and dimensions.get("height_mm") and dimensions.get("depth_mm")):
        checklist.append("📏 Указать габариты упаковки (Ш×В×Д в мм) — нужно для расчёта доставки")

    # Category and attributes
    checklist.append("🔍 Проверить точную категорию Ozon — от неё зависит видимость в поиске")
    checklist.append("📝 Добавить все обязательные атрибуты категории в кабинете Ozon")

    # SEO
    checklist.append("🏷️ Проверить ключевые слова — совпадают ли с тем, что ищут покупатели")
    checklist.append("🔎 Убедиться, что ключевые слова не дублируют название дословно — добавьте синонимы")

    # Competitor comparison
    checklist.append("💰 Сравнить цену с конкурентами в выдаче Ozon")

    # Content quality
    checklist.append("📖 Прочитать описание от имени покупателя — понятно ли, зачем покупать?")
    checklist.append("✅ Убедиться, что название передаёт тип товара + бренд + ключевое свойство")
    checklist.append("📝 Перечитать описание на ошибки и опечатки — проверьте факты и цифры")

    # Compliance
    checklist.append("⚠️ Проверить соответствие требованиям категории Ozon (маркировка, документы)")

    return checklist


def _draft_missing_fields(draft: OzonCardDraft | None) -> list[str]:
    if not draft:
        return ["карточка не собрана"]
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
    return missing


def _build_batch_counts(items: list[OzonCardBatchItem]) -> dict[str, int]:
    counts = {"total": len(items), "ready": 0, "needs_review": 0, "error": 0}
    for item in items:
        if item.status == "error":
            counts["error"] += 1
        elif _draft_missing_fields(item.draft):
            counts["needs_review"] += 1
        else:
            counts["ready"] += 1
    return counts


def _human_batch_status(status: str) -> str:
    if status == "ready":
        return "Готово к проверке"
    if status == "needs_review":
        return "Нужна доработка"
    if status == "error":
        return "Ошибка"
    return status or "Неизвестно"


def _write_header_row(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _style_batch_sheet(ws) -> None:
    ws.freeze_panes = "A2"
    widths = {
        1: 6,
        2: 20,
        3: 28,
        4: 28,
        5: 52,
        6: 28,
        7: 18,
        8: 12,
        15: 48,
        16: 44,
        17: 70,
        18: 52,
        19: 52,
        20: 60,
        21: 42,
    }
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _apply_competitor_context(draft: OzonCardDraft, competitors: list[dict]) -> None:
    if not competitors:
        return

    prices = [item["price"] for item in competitors if isinstance(item.get("price"), int)]
    words = _top_competitor_words(competitors)
    for word, _ in words[:10]:
        if word not in draft.keywords:
            draft.keywords.append(word)
    draft.keywords = _sanitize_keywords(draft.keywords, brand=draft.brand, limit=30)

    draft.competitors = [
        {
            "marketplace": item.get("marketplace") or "unknown",
            "name": (item.get("name") or "")[:200],
            "price": item.get("price") if isinstance(item.get("price"), (int, float)) else None,
            "old_price": item.get("old_price") if isinstance(item.get("old_price"), (int, float)) else None,
            "discount_pct": item.get("discount_pct") if isinstance(item.get("discount_pct"), (int, float)) else None,
            "rating": item.get("rating") if isinstance(item.get("rating"), (int, float)) else None,
            "reviews_count": item.get("reviews_count") if isinstance(item.get("reviews_count"), int) else None,
            "availability": item.get("availability") or "unknown",
            "seller_name": item.get("seller_name") or "",
            "url": item.get("url") or "",
            "image_url": item.get("image_url") or "",
        }
        for item in competitors[:30]
    ]
    by_marketplace: dict[str, int] = {}
    for item in draft.competitors:
        market = item["marketplace"]
        by_marketplace[market] = by_marketplace.get(market, 0) + 1
    parts = [f"Найдено конкурентов: {len(draft.competitors)}"]
    if by_marketplace:
        market_labels = {"wildberries": "Wildberries", "ozon": "Ozon", "yandex_market": "Яндекс Маркет"}
        parts.append(
            "по площадкам: "
            + ", ".join(
                f"{market_labels.get(market, market)} — {count}" for market, count in sorted(by_marketplace.items())
            )
        )
    if prices:
        parts.append(f"цены: {min(prices)}–{max(prices)} ₽, медиана {int(median(prices))} ₽")
        if not draft.price:
            draft.checklist.append(f"Сравнить цену с медианой конкурентов: {int(median(prices))} ₽")
    if words:
        parts.append("частые слова: " + ", ".join(word for word, _ in words[:8]))
    draft.competitor_summary = "; ".join(parts)
    if "Проверить, чем карточка отличается от конкурентов в выдаче Ozon" not in draft.checklist:
        draft.checklist.append("Проверить, чем карточка отличается от конкурентов в выдаче Ozon")


def _compact_competitors(competitors: list[dict]) -> list[dict]:
    return [
        {
            "marketplace": item.get("marketplace"),
            "name": (item.get("name") or "")[:120],
            "price": item.get("price"),
            "old_price": item.get("old_price"),
            "discount_pct": item.get("discount_pct"),
            "rating": item.get("rating"),
            "reviews_count": item.get("reviews_count"),
            "availability": item.get("availability"),
            "url": item.get("url"),
        }
        for item in competitors[:10]
    ]


_COMPETITOR_STOP_WORDS = {
    "для",
    "или",
    "без",
    "при",
    "под",
    "над",
    "товар",
    "шт",
    "набор",
    "ozon",
    "wb",
    "wildberries",
    "черный",
    "белый",
}


def _top_competitor_words(competitors: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in competitors:
        name = item.get("name") or ""
        for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", name.lower()):
            if word in _COMPETITOR_STOP_WORDS or word.isdigit():
                continue
            counts[word] = counts.get(word, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]


def _product_type_stems(draft: OzonCardDraft) -> set[str]:
    """Word stems (first 5 chars) describing what the product *is*, excluding the brand."""
    brand_tokens = {w.lower()[:5] for w in re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", draft.brand or "")}
    stems: set[str] = set()
    for source in (draft.name, draft.category_hint or ""):
        for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", source.lower()):
            if word in _COMPETITOR_STOP_WORDS or word.isdigit():
                continue
            stem = word[:5]
            if stem in brand_tokens:
                continue
            stems.add(stem)
    return stems


def _filter_relevant_competitors(competitors: list[dict], draft: OzonCardDraft) -> list[dict]:
    """Drop marketplace search hits that only matched on the brand name, not the product type.

    Competitor search (build_ozon_card_search_query) sends the product name as a plain
    full-text query to real marketplace search - a brand name that collides with an
    unrelated real product (e.g. a test brand matching a famous shampoo brand) returns
    results from a completely different category. Require at least one shared word stem
    with the product's own name/category (brand words excluded on both sides) before
    trusting a result as an actual competitor.
    """
    type_stems = _product_type_stems(draft)
    if not type_stems:
        return competitors

    aliases: set[str] = set()
    product_text = f"{draft.name} {draft.category_hint or ''}".lower()
    if any(token in product_text for token in ("наушник", "гарнитур")):
        aliases.update({"гарнит", "headse", "earbud", "tws"})
    if any(token in product_text for token in ("кабел", "провод", "шнур")):
        aliases.update({"кабел", "провод", "шнур", "cable"})
    if any(token in product_text for token in ("чехол", "кейс")):
        aliases.update({"чехол", "кейс", "case"})

    relevant = []
    seen_urls: set[str] = set()
    for item in competitors:
        name = (item.get("name") or "").lower()
        comp_tokens = {word[:5] for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", name)}
        comp_tokens.update(
            word[:5] for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", str(item.get("category") or "").lower())
        )
        if not (comp_tokens & (type_stems | aliases)):
            continue
        url = (item.get("url") or "").split("?", 1)[0].rstrip("/").lower()
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        relevant.append(item)
    return relevant


TECH_SEO_TERMS = {
    "https",
    "http",
    "www",
    "webp",
    "images",
    "image",
    "img",
    "jpg",
    "jpeg",
    "png",
    "catalog",
    "wildberries",
    "ozon",
    "basket",
    "vol",
    "ru",
    "product",
    "api",
    "создать",
    "создай",
    "сделать",
    "сделай",
    "карточку",
    "карточка",
    "товара",
    "максимально",
    "привлекательную",
    "привлекательный",
    "сильным",
    "сильный",
    "выгодами",
    "выгоды",
    "понятным",
    "описанием",
    "описание",
    "задача",
}
RU_STOP_WORDS = {
    "для",
    "или",
    "без",
    "это",
    "под",
    "при",
    "товар",
    "цена",
    "руб",
    "за",
    "как",
    "что",
    "его",
    "нее",
    "она",
}


def _remove_service_noise(text: str) -> str:
    value = text or ""
    # Extract and preserve "Из источника:" sections before cleaning
    source_facts = re.findall(r"Из источника:.*", value, flags=re.I)

    value = re.sub(r"https?://\S+", " ", value, flags=re.I)
    # Remove task/source instructions but preserve "Из источника:" facts section
    value = re.sub(
        r"\b(?:задача|старая цена|скидка)\s*[:=-].*(?:\n|$)",
        " ",
        value,
        flags=re.I,
    )
    # Remove standalone "источник:" lines (not "Из источника:")
    value = re.sub(
        r"(?<!Из )источник\s*[:=-]\s*\S+.*(?:\n|$)",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"\bсозда(?:ть|й)\s+максимально\s+привлекательн\w+\s+карточк\w+.*",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+", " ", value).strip()
    # Re-append preserved source facts if they were stripped
    for fact in source_facts:
        if fact not in value:
            value = f"{value}\n{fact}" if value else fact
    return value.strip()


def _sanitize_keywords(words: list[str], brand: str, limit: int = 30) -> list[str]:
    brand_tokens = {w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", brand or "")}
    result: list[str] = []
    seen: set[str] = set()
    for raw in words:
        word = _clean(raw).lower().strip("-_")
        if not word or word in seen:
            continue
        if any(ch.isdigit() for ch in word):
            continue
        if word in TECH_SEO_TERMS or word in RU_STOP_WORDS:
            continue
        has_latin = bool(re.search(r"[a-z]", word))
        has_cyr = bool(re.search(r"[а-яё]", word))
        if has_latin and word not in brand_tokens:
            continue
        if not has_cyr and word not in brand_tokens:
            continue
        result.append(word)
        seen.add(word)
        if len(result) >= limit:
            break
    return result


def _build_selling_points(title: str) -> list[str]:
    """Build product-specific selling points.

    Each point should answer: "Why should I buy THIS product?"
    Avoid generic phrases like "удобен для ежедневного использования".
    """
    base = title.strip() or "Товар"
    low = base.lower()
    points = []

    # Detect product category and build specific points
    if any(t in low for t in ("магни", "цитрат", "витамин", "капсул", "таблет", "бад")):
        points = [
            "Форма выпуска и дозировка указаны прямо в карточке — сравнивать с аналогами просто",
            "Состав и рекомендации по применению — вся ключевая информация в одном месте",
            "Упаковка рассчитана на курс — не нужно пересчитывать дозы самостоятельно",
        ]
    elif any(t in low for t in ("книга", "книж", "roman", "учебник")):
        points = [
            "Формат и объём издания — сразу видно, что именно вы получаете",
            "Язык и количество страниц — можно оценить время чтения",
            "Актуальное содержание — проверьте оглавление и аннотацию",
        ]
    elif any(t in low for t in ("кабел", "провод", "шнур")):
        points = [
            "Тип разъёма и совместимость — подойдёт ли к вашему устройству",
            "Длина кабеля — выбирайте под свою задачу",
            "Материал и качество изготовления — надёжность на каждый день",
        ]
    elif any(t in low for t in ("наушник", "гарнитур")):
        points = [
            "Тип подключения — Bluetooth, провод, USB",
            "Комфорт ношения — вес, конструкция, амбушюры",
            "Качество звука — частотный диапазон, шумоподавление",
        ]
    elif any(t in low for t in ("чехол", "защитн")):
        points = [
            "Точная подгонка под модель устройства",
            "Материал и уровень защиты от повреждений",
            "Доступ к разъёмам и кнопкам без снятия чехла",
        ]
    elif any(t in low for t in ("зарядн", "адаптер", "блок")):
        points = [
            "Мощность зарядки — сколько времени до полной зарядки",
            "Тип разъёма и совместимость с вашими устройствами",
            "Защита от перегрева и короткого замыкания",
        ]
    elif any(t in low for t in ("коврик", "йог")):
        points = [
            "Размер и толщина — подходит ли для ваших упражнений",
            "Материал — не скользит, легко моется",
            "Плотность и амортизация — комфорт для суставов",
        ]
    # Clothing
    elif any(
        t in low
        for t in ("футбол", "рубашк", "блуз", "джинс", "брюки", "штаны", "курт", "плащ", "пальто", "платье", "юбка")
    ):
        points = [
            "Состав ткани и рекомендации по уходу — стирайте и гладьте правильно",
            "Размерная сетка — сверьте свои мерки перед заказом",
            "Крой и посадка — для какого типа фигуры подходит",
        ]
    # Food / drinks
    elif any(t in low for t in ("чай", "кофе", "сок", "вода", "шоколад", "конфет", "печенье", "бисквит", "снек")):
        points = [
            "Состав и натуральность ингредиентов — что внутри",
            "Вкус и особенности — для каких предпочтений подходит",
            "Срок годности и условия хранения — сохранность продукта",
        ]
    # Home goods
    elif any(t in low for t in ("кресл", "стул", "лампа", "светильник", "мебел", "подушк", "одеял")):
        points = [
            "Дизайн и габариты — подходит ли для вашего интерьера",
            "Материал и долговечность — как долго прослужит",
            "Функциональность — какие задачи решает в быту",
        ]
    # Sports
    elif any(t in low for t in ("спорт", "фитнес", "тренаж", "мяч", "гантел", "скакалк")):
        points = [
            "Производительность — для какого уровня тренировок подходит",
            "Комфорт и эргономика — удобство во время занятий",
            "Прочность и износостойкость — как долго сохраняет свойства",
        ]
    else:
        # Generic but useful points
        points = [
            "Характеристики указаны в карточке — сравнивайте перед покупкой",
            "Фото показывают реальный товар — оцените дизайн и качество",
            "Проверьте комплектацию и габариты перед заказом",
        ]

    return points[:4]


def _map_to_ozon_category_path(category: str) -> str:
    low = (category or "").lower()
    mapping = [
        ("книг", "Книги/Художественная литература"),
        ("магни", "Красота и здоровье/Витамины и БАДы/Минералы"),
        ("минерал", "Красота и здоровье/Витамины и БАДы/Минералы"),
        ("мебел", "Дом и сад/Мебель/Кресла"),
        ("кресл", "Дом и сад/Мебель/Кресла"),
        ("коврик", "Спорт и отдых/Фитнес и йога/Коврики для йоги"),
        ("йог", "Спорт и отдых/Фитнес и йога/Коврики для йоги"),
        ("кабел", "Электроника/Аксессуары для смартфонов/Кабели и переходники"),
        ("держател", "Автотовары/Аксессуары/Держатели для телефонов"),
        ("наушник", "Электроника/Аудиотехника/Наушники и гарнитуры"),
        ("чехол", "Электроника/Аксессуары для смартфонов/Чехлы"),
        ("витамин", "Красота и здоровье/Витамины и БАДы/Витамины"),
        ("бад", "Красота и здоровье/Витамины и БАДы"),
        ("капсул", "Красота и здоровье/Витамины и БАДы"),
        ("таблет", "Красота и здоровье/Витамины и БАДы"),
    ]
    for token, ozon_path in mapping:
        if token in low:
            return ozon_path
    return category


def _category_keyword_whitelist(category: str | None) -> list[str]:
    low = (category or "").lower()
    rules: list[tuple[tuple[str, ...], list[str]]] = [
        (
            ("книга", "книж", "литература", "чтение", "автор", "издатель"),
            ["книга", "автор", "издатель", "чтение", "литература", "саморазвитие"],
        ),
        (
            ("витамин", "бад", "магни", "капсул", "таблет", "минерал"),
            ["магни", "цитрат", "витамин", "капсул", "таблет", "минерал", "бад"],
        ),
        (("коврик", "йога", "фитнес"), ["коврик", "йог", "фитнес", "нескольз", "толщин", "упражнен"]),
        (("кабел", "смартфон", "аксессуар"), ["кабел", "заряд", "usb", "type", "lightning", "micro", "разъем"]),
        (("мебел", "кресл"), ["кресл", "эргоном", "офис", "обивк", "подлокот", "спинк"]),
        (("держател", "автотовар"), ["держател", "телефон", "магнит", "панел", "авто"]),
        (("наушник", "аудио"), ["науш", "гарнитур", "звук", "шумоподав", "микрофон"]),
        (("чехл",), ["чехл", "защит", "смартфон", "материал", "удар"]),
        (("маникюр", "педикюр", "красота"), ["кусач", "маникюр", "педикюр", "лезви", "ногт"]),
    ]
    for triggers, roots in rules:
        if any(trigger in low for trigger in triggers):
            return roots
    return []
