"""Pure text/NLU helper functions extracted from app/bot.py."""

import re

from app.task_intents import (
    TaskType,
    _looks_like_page_classification_training,
    detect_task_intent,
)
from app.telegram_url_utils import extract_urls


def _clean_natural_payload(payload: str) -> str:
    payload = re.sub(r"^[\s:,\-–—]+", "", payload or "").strip()
    return re.sub(r"\s+", " ", payload)


def _is_vague_product_reference(payload: str) -> bool:
    normalized = re.sub(r"\s+", " ", (payload or "").strip().lower())
    normalized = re.sub(r"\b(?:цена|стоимость|за|по)\s*[\d\s]{1,8}\s*(?:₽|руб\.?|р\.?)?", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return bool(
        re.fullmatch(
            r"(?:мо[йяе]|моего|мою|мой|этот|эта|это|эту|данный|данную|данное|тот|та|то|его|её|ее)(?:\s+товар\w*)?",
            normalized,
        )
    )


def _mentions_card(text: str) -> bool:
    return bool(re.search(r"\b(карточ\w*|ozon[\s_-]*card|озон[\s_-]*карт)\b", text or ""))


def _is_meta_task_instruction(text: str) -> bool:
    low = (text or "").lower()
    return bool(
        re.search(r"\b(повтори|повторить|сделай\s+ещ[её]\s+раз)\b.*\b(последн\w*|прошл\w*|предыдущ\w*)\s+задан", low)
        or re.search(r"\b(последн\w*|прошл\w*|предыдущ\w*)\s+задан", low)
        or re.search(r"\b(составь|сделай|напиши)\s+план\s+действ", low)
    )


def _mentions_wildberries(text: str) -> bool:
    return bool(
        re.search(
            r"(wildberries\.ru|wb\.ru|wildberries|(?<![a-zа-я0-9])wb(?![a-zа-я0-9])|вайлдберриз|\bвб\b)",
            text or "",
            flags=re.I,
        )
    )


def _clean_marketplace_search_query(text: str) -> str:
    query = re.sub(r"https?://\S+", " ", text or "", flags=re.I)
    query = re.sub(r"\b(?:иди|перейди|зайди)\s+(?:по|на)\s+(?:этой|эту)?\s*ссылк\w*", " ", query, flags=re.I)
    query = re.sub(r"\b(?:по|на)\s+(?:этой|эту)\s+ссылк\w*", " ", query, flags=re.I)
    query = re.sub(r"\b(?:на|в)\s+(?:wildberries|вайлдберриз|вб|wb)\b", " ", query, flags=re.I)
    query = re.sub(r"\bwildberries\b|\bвайлдберриз\b|\bwb\b|\bвб\b", " ", query, flags=re.I)
    query = re.sub(r"\bтакие\s+", " ", query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip(" \t\r\n.,;:!?-–—")
    query = re.sub(r"\s+\b(?:на|в)\b$", "", query, flags=re.I).strip(" \t\r\n.,;:!?-–—")
    return query


def _clean_product_search_query(text: str) -> str:
    query = re.sub(r"https?://\S+", " ", text or "", flags=re.I)
    query = re.sub(r"\s+", " ", query).strip(" \t\r\n.,;:!?-–—")
    return query


def _extract_wildberries_card_search_query(text: str) -> str:
    raw = re.sub(r"https?://\S+", " ", text or "", flags=re.I)
    patterns = [
        r"(?:найди|найти|поищи|ищи)\s+(?:там\s+)?(.+?)(?:\s+и\s+(?:созд|сдел|состав|собер|заполн|подготов)|$)",
        r"(?:для|по|на)\s+(.+?)(?:\s+и\s+(?:созд|сдел|состав|собер|заполн|подготов)|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I | re.S)
        if match:
            query = _clean_marketplace_search_query(match.group(1))
            query = re.sub(r"\b(?:сам\w*\s+)?(?:красив\w*|лучш\w*)\b", " ", query, flags=re.I)
            query = re.sub(r"\bкарточк\w*\s+товар\w*\b|\bкарточк\w*\b", " ", query, flags=re.I)
            query = re.sub(r"\s+", " ", query).strip(" \t\r\n.,;:!?-–—")
            if query:
                return query
    return _clean_marketplace_search_query(raw)


def _extract_natural_price(text: str) -> int | None:
    patterns = [
        r"(?:цена|стоимость)\s*[:=-]?\s*([\d\s]{2,8})(?:₽|руб|р)?",
        r"(?:за|по)\s*([\d\s]{2,8})(?:₽|руб|р)?",
        r"([\d\s]{2,8})\s*(?:₽|руб|р)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.I)
        if match:
            value = int(re.sub(r"\D", "", match.group(1)) or "0")
            if 1 <= value <= 50_000_000:
                return value
    return None


def _build_card_task_from_combined_request(text: str) -> str | None:
    match = re.search(
        r"(?:конкурент\w*|выдач\w*|рын\w*)\s+(?:для|по|на)\s+(.+?)(?:\s+и\s+|\s*,\s*|\.\s*)",
        text or "",
        flags=re.I,
    )
    if not match:
        return None
    product = _clean_natural_payload(match.group(1))
    product = re.sub(r"\b(?:набросай|составь|собери|сделай|карточ\w*).*$", "", product, flags=re.I).strip(" ,.;:-")
    if not product:
        return None
    lines = [f"товар: {product}"]
    price = _extract_natural_price(text)
    if price:
        lines.append(f"цена: {price}")
    return "\n".join(lines)


# ── Technical spec / training constants ────────────────────────────────────────

_TECHNICAL_SPEC_FIELD_NAMES = {
    "title",
    "price",
    "availability",
    "rating",
    "product_url",
    "product url",
    "url",
    "upc",
    "product_type",
    "product type",
    "tax",
    "number_of_reviews",
    "number of reviews",
    "description",
}


_TECHNICAL_SPEC_MARKERS = (
    "task:",
    "задача",
    "requirements:",
    "требован",
    "обязательно",
    "нужно",
    "надо",
    "result",
    "результат",
    "сохран",
    "собрать",
    "проанализ",
    "csv",
    "html",
    "parser",
    "scraper",
    "scraping",
    "парсер",
    "парсинг",
    "logging",
    "логирован",
    "delay",
    "задерж",
    "errors",
    "ошиб",
)


_TRAINING_BLOCK_MARKERS = (
    "сначала определи:",
    "верни:",
    "проверь:",
    "требования:",
    "поля:",
    "задача:",
)


def _looks_like_training_prompt(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if _looks_like_page_classification_training(raw, low):
        return True
    if "\n" not in raw:
        return False
    return any(marker in low for marker in _TRAINING_BLOCK_MARKERS)


def _is_training_protocol_fragment(text: str) -> bool:
    raw = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", (text or "").strip().lower())
    raw = raw.strip("`'\" :;,.")
    if not raw:
        return False
    if raw in {
        "сначала определи",
        "верни",
        "проверь",
        "требования",
        "поля",
        "задача",
        "status",
        "warnings",
        "warning",
        "task_type",
        "page_structure",
        "confidence",
        "intent",
        "action",
        "url",
        "http_status",
        "почему ты так решил",
    }:
        return True
    protocol_tokens = {
        "status",
        "warnings",
        "task_type",
        "page_structure",
        "confidence",
        "intent",
        "action",
        "url",
        "http_status",
    }
    if re.search(r"[а-яё]", raw, flags=re.I):
        return False
    tokens = set(re.findall(r"[a-z_]+", raw))
    return bool(tokens) and tokens.issubset(protocol_tokens)


def _looks_like_single_technical_spec(text: str) -> bool:
    # Product card briefs are one structured task, not one task per field.
    # This also covers the common Telegram flow where the FSM state was lost
    # after /ozon_card and the catch-all handler receives the multiline text.
    product_field_lines = 0
    has_product_name = False
    for line in (text or "").splitlines():
        match = re.match(r"^\s*([а-яёa-z_ ]+)\s*[:=]\s*.+$", line, flags=re.I)
        if not match:
            continue
        field = re.sub(r"\s+", " ", match.group(1).strip().lower())
        if field in {
            "товар",
            "название товара",
            "название",
            "product",
            "product name",
            "бренд",
            "brand",
            "категория",
            "category",
            "цена",
            "price",
            "цвет",
            "color",
            "материал",
            "material",
            "вес",
            "weight",
            "размер",
            "size",
            "подключение",
            "connection",
            "характеристики",
            "параметры",
            "модель",
            "артикул",
            "комплектация",
            "назначение",
        }:
            product_field_lines += 1
            if field in {"товар", "название товара", "product", "product name"}:
                has_product_name = True
    if has_product_name or product_field_lines >= 2:
        return True

    if _looks_like_training_prompt(text):
        return True

    if detect_task_intent(text).type is TaskType.SCRAPING:
        return True

    raw = (text or "").strip()
    if "\n" not in raw or not extract_urls(raw):
        return False

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    field_lines = 0
    list_item_lines = 0
    for line in lines:
        if re.match(r"^(?:[-*•]|\d+[.)])\s+\S+", line):
            list_item_lines += 1
        normalized = line.strip(" \t-*•0123456789.)").strip("`'\"").lower()
        normalized = normalized.rstrip(":")
        if normalized in _TECHNICAL_SPEC_FIELD_NAMES:
            field_lines += 1

    if field_lines >= 2:
        return True

    low = raw.lower()
    marker_count = sum(1 for marker in _TECHNICAL_SPEC_MARKERS if marker in low)
    if list_item_lines >= 2 and marker_count >= 1:
        return True

    return marker_count >= 2


def split_natural_tasks(text: str) -> list[str]:
    if _looks_like_single_technical_spec(text):
        return [(text or "").strip()]

    tasks = []
    for line in (text or "").splitlines():
        task = line.strip(" \t-•")
        task = re.sub(r"[.;]+$", "", task).strip()
        if task:
            tasks.append(task)
    return tasks


def _collect_batch_card_sources_from_tasks(tasks: list[str]) -> list[str] | None:
    from app.bot import _split_batch_card_sources, parse_natural_request

    sources = []
    for task in tasks:
        intent, payload = parse_natural_request(task)
        if intent == "ozon_card":
            sources.append(str(payload))
        elif intent == "ozon_card_urls":
            sources.extend(payload)
        elif intent == "ozon_batch_cards":
            sources.extend(_split_batch_card_sources(str(payload)))
        else:
            return None
    return sources if len(sources) > 1 else None


def _split_card_and_other_tasks(tasks: list[str]) -> tuple[list[str], list[str]]:
    from app.bot import _split_batch_card_sources, parse_natural_request

    card_sources = []
    other_tasks = []
    for task in tasks:
        intent, payload = parse_natural_request(task)
        if intent == "ozon_card":
            card_sources.append(str(payload))
        elif intent == "ozon_card_urls":
            card_sources.extend(payload)
        elif intent == "ozon_batch_cards":
            card_sources.extend(_split_batch_card_sources(str(payload)))
        else:
            other_tasks.append(task)
    return card_sources, other_tasks
