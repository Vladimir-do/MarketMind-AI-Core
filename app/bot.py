import asyncio
import html
import io
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import and_, func, select, desc

from app.config import ADMIN_IDS, PROXY, TELEGRAM_PROXY, logger
from app.database import Database, Product, PriceHistory, url_to_hash
from app.parsers.yandex_market import is_yandex_market_url
from app.worker import worker_add_urls, worker_update_all
from app.resilience import resilience
from app.agent import PriceAgent
from app.searcher import ozon_search_blocked_message, search_ozon
from app.task_intents import (
    ContextSession,
    StructuredTask,
    TaskType,
    _looks_like_page_classification_training,
    detect_task_intent,
)
from app.task_planner import SkillStatus, TaskPlanner
from app.agent_loop import build_agent_loop, stage_label_ru
from app.skill_notes import create_skill_note_proposal, list_pending_skill_proposals
from app.parsers.funpay import (
    build_funpay_search_query,
    fetch_funpay_offer,
    format_funpay_offer_summary,
    is_funpay_offer_url,
)
from app.card_profiles import load_profile, list_profiles
from app.telegram_diagnostics import (
    mask_proxy_url as _mask_proxy_url,
    probe_dns as _probe_dns,
    probe_https as _probe_https,
    probe_tcp as _probe_tcp,
)
from app.telegram_messages import (
    command_limit as _message_command_limit,
    format_blocked_patterns,
    format_marketplace_health,
    format_network_diagnostics,
    format_product_list,
    format_recent_scrape_attempts,
    format_status_message,
)
from app.telegram_exports import send_html_report, send_price_export
from app.telegram_ai_reports import (
    build_market_overview_message,
    build_price_alerts_message,
    build_price_forecast_message,
)
from app.telegram_card_research import build_card_research_message
from app.telegram_card_tasks import (
    build_card_task_from_product as _build_card_task_from_product,
    build_card_task_from_url as _build_card_task_from_url,
)
from app.telegram_runtime import run_telegram_polling, telegram_reconnect_delay
from app.universal_parsing_core.schemas.page_structure import PageStructure

# ── Бот ───────────────────────────────────────────────────────────────────────
bot: Bot | None = None
dp = Dispatcher(storage=MemoryStorage())

db = Database()
agent = PriceAgent(db)
parser_lock = asyncio.Lock()
MAX_NATURAL_TASKS = 300
MAX_BATCH_CARD_SOURCES = 300
DEFAULT_PROFILE_NAME = "default"
CHAT_PROFILES: dict[int, str] = {}
CHAT_CONTEXTS: dict[int, ContextSession] = {}
task_planner = TaskPlanner()


# ── FSM ───────────────────────────────────────────────────────────────────────
class Form(StatesGroup):
    waiting_urls   = State()
    waiting_search = State()
    waiting_search_results = State()  # ожидание выбора из результатов поиска
    waiting_compare = State()
    waiting_reviews = State()
    waiting_ozon_card = State()
    waiting_ozon_batch = State()
    waiting_card_research = State()


# ── Helpers ───────────────────────────────────────────────────────────────────
def allowed(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


async def ensure_allowed(message: types.Message) -> bool:
    if allowed(message.from_user.id):
        return True
    await message.answer("⛔ Доступ запрещён.")
    return False


def validate_search_query(query: str) -> tuple[bool, str | None]:
    parsed = urlparse(query.strip())
    if parsed.scheme not in {"http", "https"}:
        return True, None

    host = (parsed.netloc or "").lower()
    if "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(query):
        return False, (
            "Это ссылка на товар. Для ссылок используйте /add, "
            "а для /search отправьте обычное название товара."
        )
    return False, (
        f"Это ссылка на неподдерживаемый сайт ({host or 'unknown'}). "
        "Сейчас я ищу только по названию товара на Ozon. "
        "Пришлите название, например: <code>держатель для телефона</code>."
    )


def extract_urls(text: str) -> list[str]:
    return [url.rstrip(".,);]}>") for url in re.findall(r"https?://\S+", text or "", flags=re.I)]


def is_supported_marketplace_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(url)


def extract_supported_urls(text: str) -> list[str]:
    return [url for url in extract_urls(text) if is_supported_marketplace_url(url)]


def extract_command_payload(text: str | None, command: str) -> str:
    match = re.match(rf"^/{re.escape(command)}(?:@\w+)?(?:\s+(.*))?$", text or "", flags=re.I | re.S)
    return (match.group(1) or "").strip() if match else ""


def get_active_profile_name(chat_id: int) -> str:
    return CHAT_PROFILES.get(chat_id, DEFAULT_PROFILE_NAME)


def get_active_profile(chat_id: int) -> dict:
    profile = load_profile(get_active_profile_name(chat_id))
    return profile.as_dict()


def _clean_natural_payload(payload: str) -> str:
    payload = re.sub(r"^[\s:,\-–—]+", "", payload or "").strip()
    return re.sub(r"\s+", " ", payload)


def _is_vague_product_reference(payload: str) -> bool:
    normalized = re.sub(r"\s+", " ", (payload or "").strip().lower())
    normalized = re.sub(r"\b(?:цена|стоимость|за|по)\s*[\d\s]{1,8}\s*(?:₽|руб\.?|р\.?)?", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return bool(re.fullmatch(r"(?:мо[йяе]|моего|мою|мой|этот|эта|это|эту|данный|данную|данное|тот|та|то|его|её|ее)(?:\s+товар\w*)?", normalized))


def _mentions_card(text: str) -> bool:
    return bool(re.search(r"\b(карточ\w*|ozon[\s_-]*card|озон[\s_-]*карт)\b", text or ""))


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


def get_chat_context(chat_id: int) -> ContextSession:
    context = CHAT_CONTEXTS.get(chat_id)
    if context is None:
        context = ContextSession()
        CHAT_CONTEXTS[chat_id] = context
    return context


def _format_page_classification_reason(result) -> str:
    signals = result.raw_snapshot.get("page_structure_signals", {}) if result.raw_snapshot else {}
    structure = result.page_structure.value
    reasons: list[str] = []
    if structure == "catalog":
        product_pods = signals.get("product_pod_count", 0)
        detail_links = signals.get("detail_link_count", 0)
        prices = signals.get("price_count", 0)
        if product_pods:
            reasons.append(f"найдены повторяющиеся карточки товаров: {product_pods}")
        if detail_links:
            reasons.append(f"есть ссылки на страницы деталей: {detail_links}")
        if prices:
            reasons.append(f"найдены цены: {prices}")
        if signals.get("has_pagination"):
            reasons.append("есть пагинация или ссылка на следующую страницу")
        return "; ".join(reasons) or "страница похожа на список однотипных сущностей"
    if structure == "single":
        return "похоже на одну основную карточку: один заголовок, одна цена и мало ссылок"
    if structure == "article":
        return "много текста и есть признаки статьи: article/time/author"
    if structure == "empty":
        return "в HTML/body почти нет полезного содержимого"
    return "полезный HTML есть, но структурных признаков пока недостаточно для уверенной классификации"


async def classify_page_before_parsing(url: str) -> str:
    from app.universal_parsing_core.parsers.universal_html import UniversalHtmlParser

    status, html_text = await fetch_html(url)
    result = UniversalHtmlParser().parse(url, html=html_text)
    warnings = html.escape("; ".join(result.warnings) if result.warnings else "-")
    reason = html.escape(_format_page_classification_reason(result))
    return (
        "Намерение: page_classification_training\n"
        "Действие: classify_page_before_parsing\n"
        f"Адрес: {html.escape(url)}\n"
        f"HTTP-статус: {status}\n"
        f"task_type: {result.task_type.value}\n"
        f"page_structure: {result.page_structure.value}\n"
        f"next_strategy: {result.next_strategy or '-'}\n"
        f"confidence: {result.confidence:.2f}\n"
        f"Предупреждения: {warnings}\n"
        f"Почему так решил: {reason}"
    )


async def fetch_html(url: str) -> tuple[int, str]:
    from app.generic_scraper import fetch_html as _fetch_html

    return await _fetch_html(url)


@dataclass(frozen=True, slots=True)
class ScrapingPreflightDecision:
    allowed: bool
    http_status: int
    domain_task_type: str
    task_type: str
    page_structure: str
    confidence: float
    next_strategy: str
    fetcher: str
    reason: str
    warnings: tuple[str, ...] = ()


def build_scraping_preflight_decision(task: StructuredTask, html_text: str, *, http_status: int = 0) -> ScrapingPreflightDecision:
    from app.universal_parsing_core.parsers.universal_html import UniversalHtmlParser

    result = UniversalHtmlParser().parse(task.target_url or "", html=html_text)
    structure = result.page_structure
    domain_task_type = str(task.parameters.get("task_type") or result.task_type.value)
    explicit_fields = bool(task.fields)
    allowed_structures = {PageStructure.CATALOG, PageStructure.SINGLE, PageStructure.MIXED}

    browser_structures = {PageStructure.EMPTY, PageStructure.UNKNOWN_JS}
    non_generic_task_types = {"api_source", "freelance_project", "article", "text_collection"}
    allowed = structure in allowed_structures
    fetcher = "html"
    if domain_task_type in non_generic_task_types:
        allowed = False
    if structure is PageStructure.ARTICLE:
        allowed = False
    if structure in {PageStructure.UNKNOWN}:
        allowed = False
    if structure in browser_structures and result.next_strategy == "browser" and domain_task_type not in non_generic_task_types:
        allowed = True
        fetcher = "browser"
    if explicit_fields and structure in allowed_structures and domain_task_type not in non_generic_task_types:
        allowed = True

    if allowed:
        if fetcher == "browser":
            reason = f"page_structure={structure.value}: static HTML needs browser rendering before extraction"
        else:
            reason = "page structure is compatible with generic extraction"
    elif domain_task_type == "api_source":
        reason = "task_type=api_source: generic HTML product scraping is skipped; use API parsing"
    elif domain_task_type == "freelance_project":
        reason = "task_type=freelance_project: this needs a project schema, not product/catalog scraping"
    elif domain_task_type == "text_collection":
        reason = "task_type=text_collection: this needs text/quote extraction, not product scraping"
    elif domain_task_type == "article":
        reason = "task_type=article: this needs an article schema, not product/catalog scraping"
    elif structure is PageStructure.ARTICLE:
        reason = "page_structure=article: this is not a product/catalog page, so generic product scraping is skipped"
    elif structure is PageStructure.UNKNOWN_JS:
        reason = "page_structure=unknown_js: useful HTML exists but static structure is insufficient; use browser rendering next"
    elif structure is PageStructure.EMPTY:
        reason = "page_structure=empty: useful body content was not detected"
    else:
        reason = f"page_structure={structure.value}: generic product scraping is not safe without a clearer schema"

    return ScrapingPreflightDecision(
        allowed=allowed,
        http_status=http_status,
        domain_task_type=domain_task_type,
        task_type=result.task_type.value,
        page_structure=structure.value,
        confidence=result.confidence,
        next_strategy=str(task.parameters.get("next_strategy") or result.next_strategy or "-"),
        fetcher=fetcher,
        reason=reason,
        warnings=tuple(result.warnings),
    )


async def run_scraping_preflight(task: StructuredTask) -> ScrapingPreflightDecision:
    if not task.target_url:
        return ScrapingPreflightDecision(
            allowed=False,
            http_status=0,
            domain_task_type=str(task.parameters.get("task_type") or "unknown"),
            task_type="unknown",
            page_structure="unknown",
            confidence=0.0,
            next_strategy="ask_for_url",
            fetcher="none",
            reason="target URL is missing",
        )
    status, html_text = await fetch_html(task.target_url)
    return build_scraping_preflight_decision(task, html_text, http_status=status)


def format_scraping_preflight_decision(decision: ScrapingPreflightDecision) -> str:
    warnings = "; ".join(decision.warnings) if decision.warnings else "-"
    action = "continue_scraping" if decision.allowed else "skip_generic_scraping"
    return (
        "<b>Scraping preflight</b>\n"
        f"action: <code>{html.escape(action)}</code>\n"
        f"http_status: <code>{decision.http_status}</code>\n"
        f"domain_task_type: <code>{html.escape(decision.domain_task_type)}</code>\n"
        f"task_type: <code>{html.escape(decision.task_type)}</code>\n"
        f"page_structure: <code>{html.escape(decision.page_structure)}</code>\n"
        f"next_strategy: <code>{html.escape(decision.next_strategy)}</code>\n"
        f"fetcher: <code>{html.escape(decision.fetcher)}</code>\n"
        f"confidence: <code>{decision.confidence:.2f}</code>\n"
        f"warnings: <code>{html.escape(warnings)}</code>\n"
        f"reason: <code>{html.escape(decision.reason)}</code>"
    )


def format_structured_task_plan(task: StructuredTask) -> str:
    if task.type is TaskType.REPAIR:
        plan = task_planner.build_plan(task)
        agent_loop = build_agent_loop(task)
        lines = ["рџ›  <b>РџРѕРЅСЏР» repair-Р·Р°РґР°С‡Сѓ.</b>"]
        if task.target_url:
            lines.append(f"Р¦РµР»СЊ: <code>{html.escape(task.target_url)}</code>")
        if task.parameters:
            for key in ("failure_area", "severity", "blast_radius", "evidence_types", "verification_scope", "safety_gates"):
                if key in task.parameters:
                    lines.append(f"{html.escape(key)}: <code>{html.escape(str(task.parameters[key]))}</code>")
            if task.parameters.get("last_error_text"):
                lines.append(f"last_error_text: <code>{html.escape(str(task.parameters['last_error_text'])[:500])}</code>")
            if task.parameters.get("last_validation_warnings"):
                lines.append(f"last_validation_warnings: <code>{html.escape(str(task.parameters['last_validation_warnings'])[:500])}</code>")
        lines.append("")
        lines.append("<b>Р¦РёРєР» СЂРµРјРѕРЅС‚Р°:</b>")
        lines.append(" в†’ ".join(html.escape(stage_label_ru(step.stage)) for step in agent_loop.steps))
        lines.append(f"РЎС‚СЂР°С‚РµРіРёСЏ: <code>{html.escape(agent_loop.strategy)}</code>")
        lines.append("")
        for step in plan.steps:
            marker = "вњ…" if step.status is SkillStatus.AVAILABLE else "рџ§©" if step.status is SkillStatus.PLANNED else "вљ пёЏ"
            lines.append(
                f"{step.index}. {marker} <code>{html.escape(step.skill_id)}</code> "
                f"[q={step.quality_score:.2f}] вЂ” {html.escape(step.action)}"
            )
        if plan.self_critic:
            lines.append("")
            lines.append("<b>РЎР°РјРѕРїСЂРѕРІРµСЂРєР°:</b>")
            lines.extend(f"вЂў {html.escape(_localize_bot_text(check))}" for check in plan.self_critic)
        lines.append("")
        lines.append("Р”Р°Р»СЊС€Рµ РЅСѓР¶РЅРѕ РІРѕСЃРїСЂРѕРёР·РІРµСЃС‚Рё failure signal, РґРѕР±Р°РІРёС‚СЊ СЂРµРіСЂРµСЃСЃРёСЋ, РІРЅРµСЃС‚Рё С„РёРєСЃ Рё РїСЂРѕРіРЅР°С‚СЊ verification scope.")
        return "\n".join(lines)
    if task.type is TaskType.SCRAPING:
        plan = task_planner.build_plan(task)
        agent_loop = build_agent_loop(task)
        lines = ["🧠 <b>Понял scraping-задачу и сохранил контекст.</b>"]
        if task.target_url:
            lines.append(f"Цель: <code>{html.escape(task.target_url)}</code>")
        if task.fields:
            lines.append(f"Поля: <code>{html.escape(', '.join(task.fields))}</code>")
        if task.output:
            lines.append(f"Вывод: <code>{html.escape(task.output.upper())}</code>")
        if task.requirements:
            lines.append(f"Требования: <code>{html.escape(', '.join(task.requirements))}</code>")
        if task.parameters:
            params = ", ".join(f"{key}={value}" for key, value in task.parameters.items())
            lines.append(f"Параметры: <code>{html.escape(params)}</code>")
        lines.append("")
        lines.append("<b>План выполнения:</b>")
        lines.append("<b>Цикл агента:</b>")
        lines.append(" → ".join(html.escape(stage_label_ru(step.stage)) for step in agent_loop.steps))
        lines.append(f"Стратегия: <code>{html.escape(agent_loop.strategy)}</code>")
        lines.append(f"Порог confidence: <code>{agent_loop.min_confidence:.2f}</code>")
        lines.append("")
        for step in plan.steps:
            marker = "✅" if step.status is SkillStatus.AVAILABLE else "🧩" if step.status is SkillStatus.PLANNED else "⚠️"
            fallback = f" (fallback for {step.selected_for})" if step.selected_for else ""
            lines.append(
                f"{step.index}. {marker} <code>{html.escape(step.skill_id)}</code>{html.escape(fallback)} "
                f"[q={step.quality_score:.2f}] — "
                f"{html.escape(step.action)}"
            )
        if plan.self_critic:
            lines.append("")
            lines.append("<b>Самопроверка:</b>")
            lines.extend(f"• {html.escape(_localize_bot_text(check))}" for check in plan.self_critic)
        lines.append("")
        if plan.executable:
            lines.append("План можно выполнить.")
        else:
            missing = ", ".join(plan.missing_skills)
            lines.append(f"План пока нельзя выполнить: нужно подключить <code>{html.escape(missing)}</code>.")
        return "\n".join(lines)
    return "🧠 Задача распознана, но для неё ещё не подключён исполнитель."


def build_repair_diagnostic_report(task: StructuredTask) -> str:
    params = task.parameters
    lines = ["<b>Repair diagnostics</b>"]
    if task.target_url:
        lines.append(f"target_url: <code>{html.escape(task.target_url)}</code>")
    for key in (
        "previous_task_type",
        "previous_domain_task_type",
        "previous_entity_type",
        "last_error_type",
        "failure_area",
        "severity",
        "blast_radius",
        "evidence_types",
        "verification_scope",
        "safety_gates",
    ):
        if key in params:
            lines.append(f"{html.escape(key)}: <code>{html.escape(str(params[key]))}</code>")
    if params.get("last_error_text"):
        lines.append(f"last_error_text: <code>{html.escape(str(params['last_error_text'])[:500])}</code>")
    if params.get("last_validation_warnings"):
        lines.append(f"last_validation_warnings: <code>{html.escape(str(params['last_validation_warnings'])[:500])}</code>")
    suggested_tests = _repair_suggested_tests(task)
    if suggested_tests:
        lines.append(f"suggested_tests: <code>{html.escape(', '.join(suggested_tests))}</code>")
    return "\n".join(lines)


def _repair_suggested_tests(task: StructuredTask) -> list[str]:
    failure_area = str(task.parameters.get("failure_area") or "")
    if failure_area in {"intent", "page_structure"}:
        tests = ["tests/test_task_intents.py", "tests/test_agent_loop.py"]
    elif failure_area == "parser":
        tests = ["tests/test_generic_scraper.py", "tests/test_universal_html_parser.py"]
    elif failure_area == "export":
        tests = ["tests/test_exports.py"]
    elif failure_area == "network_or_antibot":
        tests = ["tests/test_searcher.py", "tests/test_parsers.py"]
    else:
        tests = ["tests/test_task_intents.py", "tests/test_task_planner.py"]
    if task.parameters.get("requires_full_tests"):
        tests.append("python -m pytest")
    tests.append("python project_skills/validate_skills.py")
    return list(dict.fromkeys(tests))


def _localize_bot_text(text: str) -> str:
    replacements = {
        "executor": "исполнитель",
        "Intent": "Намерение",
        "retry": "повторы",
        "delay": "задержка",
        "logging": "логирование",
        "error handling": "обработка ошибок",
    }
    result = text
    for source, target in replacements.items():
        result = result.replace(source, target)
    return result


async def handle_scraping_task(message: types.Message, task: StructuredTask) -> None:
    from app.generic_scraper import ScrapingError, run_scraping_task

    plan = task_planner.build_plan(task)
    await message.answer(format_structured_task_plan(task), parse_mode="HTML", disable_web_page_preview=True)
    if not plan.executable:
        return

    await parser_lock.acquire()
    try:
        mode = "с пагинацией" if task.parameters.get("pagination") or task.parameters.get("scope") == "all_pages" else "первой страницы"
        await message.answer(f"Проверяю структуру страницы перед scraping {mode}...")
        preflight = await run_scraping_preflight(task)
        if not preflight.allowed:
            logger.info(
                "Generic scraping skipped by preflight: url=%s page_structure=%s next_strategy=%s reason=%s",
                task.target_url,
                preflight.page_structure,
                preflight.next_strategy,
                preflight.reason,
            )
            get_chat_context(message.chat.id).remember_failure(
                task,
                error_text=preflight.reason,
                error_type="ScrapingPreflightBlocked",
                validation_warnings=[*preflight.warnings, preflight.reason],
            )
            await message.answer(format_scraping_preflight_decision(preflight), parse_mode="HTML", disable_web_page_preview=True)
            return
        if preflight.fetcher == "browser":
            task.parameters["browser_fallback"] = True
            task.parameters["next_strategy"] = "browser"
        await message.answer(format_scraping_preflight_decision(preflight), parse_mode="HTML", disable_web_page_preview=True)
        await message.answer(f"Запускаю scraping {mode} и готовлю CSV...")
        result = await run_scraping_task(task)
        caption = (
            "Готово: "
            f"records={result.metrics.records}, "
            f"pages={result.metrics.pages_fetched}, "
            f"http_status={result.metrics.http_status}, "
            f"bytes={result.metrics.bytes_received}"
        )
        await message.answer_document(
            types.BufferedInputFile(result.csv_bytes, filename=result.filename),
            caption=caption,
        )
        get_chat_context(message.chat.id).clear_failure()
    except ScrapingError as exc:
        logger.warning("Generic scraping task failed: %s", exc)
        get_chat_context(message.chat.id).remember_failure(
            task,
            error_text=str(exc),
            error_type=type(exc).__name__,
            validation_warnings=[item.strip() for item in str(exc).split(";") if item.strip()],
        )
        await message.answer(f"Не получилось выполнить scraping: {html.escape(str(exc))}", parse_mode="HTML")
    except Exception as exc:
        logger.exception("Unexpected generic scraping task failure")
        get_chat_context(message.chat.id).remember_failure(
            task,
            error_text=str(exc),
            error_type=type(exc).__name__,
        )
        await message.answer(f"Ошибка scraping: {html.escape(str(exc))}", parse_mode="HTML")
    finally:
        parser_lock.release()


async def handle_repair_task(message: types.Message, task: StructuredTask) -> None:
    await message.answer(format_structured_task_plan(task), parse_mode="HTML", disable_web_page_preview=True)
    await message.answer(build_repair_diagnostic_report(task), parse_mode="HTML", disable_web_page_preview=True)


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
    protocol_tokens = {"status", "warnings", "task_type", "page_structure", "confidence", "intent", "action", "url", "http_status"}
    if re.search(r"[а-яё]", raw, flags=re.I):
        return False
    tokens = set(re.findall(r"[a-z_]+", raw))
    return bool(tokens) and tokens.issubset(protocol_tokens)


def _looks_like_single_technical_spec(text: str) -> bool:
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


def parse_natural_request(
    text: str,
    context: ContextSession | None = None,
) -> tuple[str, str | list[str] | StructuredTask | None]:
    """Map plain Telegram text to a conservative bot action.

    This is deliberately rule-based: it keeps the bot predictable and avoids
    sending unexpected parser jobs for casual chat.
    """
    raw = (text or "").strip()
    if _is_training_protocol_fragment(raw):
        return "unknown", None
    structured_task = detect_task_intent(raw, context=context)
    if structured_task.type is TaskType.REPAIR:
        return "repair_task", structured_task
    if structured_task.type is TaskType.SCRAPING:
        return "scraping_task", structured_task
    if structured_task.type is TaskType.PAGE_CLASSIFICATION_TRAINING:
        return "page_classification_training", structured_task

    low = raw.lower()
    urls = extract_supported_urls(raw)

    if re.search(r"\b(обнови|обновить|проверь|проверить|перепроверь)\b", low) and re.search(r"\b(цен|цены|товар|товары|прайс)\b", low):
        return "update", None

    if re.search(r"\b(список|покажи товары|что отслеж|отслеживаем)\b", low):
        return "list", None

    if re.search(r"\b(статус|сколько товаров|состояние базы|база)\b", low):
        return "status", None

    if _mentions_card(low):
        combined_task = _build_card_task_from_combined_request(raw)
        if combined_task:
            return "ozon_card", combined_task
        if len(urls) > 1:
            return "ozon_batch_cards", raw
        if re.search(r"\b(пачк\w*|пакет\w*|массов\w*|batch|несколько|карточки|карточек)\b", low):
            if urls:
                return "ozon_batch_cards", raw
            return "ozon_batch_prompt", None

        if urls:
            return "ozon_card_urls", urls
        if re.search(r"\b(последн\w*|крайн\w*|свеж\w*)\b", low):
            return "make_card_last", None

        card_patterns = [
            r"(?:сделай|составь|собери|создай|заполни|подготовь|сгенерируй|оформи)\s+(?:мне\s+)?(?:карточк[ауи]?|ozon[\s_-]*card|озон[\s_-]*карт\w*)(?:\s+(?:для|по|на|товара))?\s+(.+)$",
            r"(?:карточк[ауи]?|ozon[\s_-]*card|озон[\s_-]*карт\w*)\s+(?:для|по|на|товар)\s+(.+)$",
        ]
        for pattern in card_patterns:
            match = re.search(pattern, raw, flags=re.I)
            if match:
                payload = _clean_natural_payload(match.group(1))
                if _is_vague_product_reference(payload):
                    return "ozon_card_prompt", None
                if payload:
                    return "ozon_card", payload
        return "ozon_card_prompt", None

    research_patterns = [
        r"^(?:проанализируй|анализ|посмотри|изучи|разбери)\s+(?:мне\s+)?(?:конкурентов|выдачу|рынок)(?:\s+(?:для|по|на|товара?))?\s+(.+)$",
        r"^(?:конкуренты|анализ конкурентов|анализ выдачи|рынок)\s+(?:для|по|на|товара?)\s+(.+)$",
    ]
    for pattern in research_patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            payload = _clean_natural_payload(match.group(1))
            if payload:
                return "card_research", payload

    if urls:
        return "add_urls", urls

    search_patterns = [
        r"^(?:найди|найти|поищи|поиск|ищи)\s+(.+)$",
        r"^(?:цена на|сколько стоит|сколько стоит\s+на озоне)\s+(.+)$",
        r"^(?:спарси|парсани|пробей)\s+(.+)$",
    ]
    for pattern in search_patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            query = match.group(1).strip()
            if query and not _is_training_protocol_fragment(query):
                return "search", query

    if (
        not extract_urls(raw)
        and len(raw) >= 4
        and not re.search(r"^(привет|здорово|ок|спасибо|help|помощь)$", low)
        and not _is_training_protocol_fragment(raw)
    ):
        return "search", raw

    return "unknown", None


def build_unhandled_message_response(text: str) -> str | None:
    urls = extract_urls(text)
    if not urls:
        return (
            "Не понял сообщение. Для поиска нажмите /search и отправьте название товара, "
            "для добавления ссылки используйте /add."
        )

    unsupported_hosts = []
    supported_urls = []
    for url in urls:
        host = (urlparse(url).netloc or "").lower()
        if "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(url):
            supported_urls.append(url)
        else:
            unsupported_hosts.append(host or "unknown")

    if unsupported_hosts:
        host_list = ", ".join(sorted(set(unsupported_hosts)))
        return (
            f"Ссылка с сайта <b>{host_list}</b> пока не поддерживается.\n\n"
            "Сейчас я умею добавлять товары по ссылкам Ozon/Wildberries через /add "
            "и искать на Ozon по названию через /search.\n"
            "Пришлите название товара, например: <code>держатель для телефона</code>."
        )

    if supported_urls:
        return "Похоже, это ссылка на товар. Чтобы добавить её в мониторинг, используйте /add."

    return None


async def notify_chat(chat_id: int, text: str):
    try:
        if bot is None:
            return
        await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"notify error: {e}")


async def handle_funpay_offer_search(message: types.Message, url: str):
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    await parser_lock.acquire()
    await message.answer("🔎 Разбираю FunPay-оффер...")
    try:
        offer = await fetch_funpay_offer(url)
        query = build_funpay_search_query(offer)
        await message.answer(
            format_funpay_offer_summary(offer, query),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        results = await search_ozon(query, max_results=5)
        if not results:
            return await message.answer("😔 На Ozon ничего не найдено по распознанному запросу.")

        lines = [f"🛍 <b>Найдено {len(results)} товаров на Ozon:</b>\n"]
        for i, result in enumerate(results, 1):
            price_str = f"{result['price']} ₽" if result.get("price") else "цена не определена"
            lines.append(
                f"{i}. <a href='{result['url']}'>{result['name'][:60]}</a>\n"
                f"   💰 {price_str}"
            )
        lines.append("\n💡 Чтобы добавить найденный товар в мониторинг, используйте /add и ссылку Ozon.")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка обработки FunPay-ссылки")
        await message.answer(f"❌ Не удалось разобрать FunPay-ссылку: {e}")
    finally:
        parser_lock.release()


# ── /start, /help ─────────────────────────────────────────────────────────────
TELEGRAM_COMMANDS = [
    types.BotCommand(command="add", description="Добавить товары по ссылкам"),
    types.BotCommand(command="update", description="Обновить цены"),
    types.BotCommand(command="list", description="Список товаров"),
    types.BotCommand(command="status", description="Статистика базы"),
    types.BotCommand(command="metrics", description="Последние попытки парсинга"),
    types.BotCommand(command="blocks", description="Anti-bot и block memory"),
    types.BotCommand(command="health", description="Состояние маркетплейсов"),
    types.BotCommand(command="search", description="Поиск товара"),
    types.BotCommand(command="report", description="HTML-отчет"),
    types.BotCommand(command="net_diag", description="Диагностика сети/proxy"),
    types.BotCommand(command="skill_note", description="Pending skill proposal"),
    types.BotCommand(command="skill_pending", description="Pending skill proposals"),
    types.BotCommand(command="skill_lesson", description="Skillpack lesson note"),
    types.BotCommand(command="ozon_card", description="Карточка Ozon"),
    types.BotCommand(command="ozon_batch_cards", description="Пачка карточек"),
    types.BotCommand(command="analyze", description="AI-анализ цен"),
    types.BotCommand(command="deals", description="Лучшие сделки"),
    types.BotCommand(command="anomalies", description="Аномалии цен"),
    types.BotCommand(command="help", description="Справка"),
]

HELP_TEXT = (
    "<b>Агент мониторинга и карточек маркетплейсов</b>\n\n"
    "<b>Основное:</b>\n"
    "/add - добавить товары по ссылкам\n"
    "/update - обновить цены\n"
    "/list - список товаров\n"
    "/status - статистика базы\n\n"
    "<b>Диагностика:</b>\n"
    "/metrics - последние попытки парсинга\n"
    "/blocks - anti-bot, block memory и adaptive skips\n"
    "/health - состояние маркетплейсов и cooldown\n"
    "/net_diag - проверка сети и proxy\n\n"
    "<b>Skillpack inbox:</b>\n"
    "/skill_note - создать pending skill proposal\n"
    "/skill_lesson - записать урок в pending proposal\n"
    "/skill_pending - показать pending proposals\n\n"
    "<b>Поиск и отчеты:</b>\n"
    "/search - найти товар по названию\n"
    "/report - HTML-отчет\n\n"
    "<b>Карточки:</b>\n"
    "/ozon_card - подготовить карточку Ozon\n"
    "/ozon_batch_cards - пачка карточек\n"
    "/card_research - исследование карточки\n"
    "/make_card_last - карточка по последнему товару\n\n"
    "<b>Аналитика:</b>\n"
    "/analyze - AI-анализ цен\n"
    "/deals - лучшие сделки\n"
    "/anomalies - подозрительные изменения цен\n"
    "/wb_deals - поиск скидок WB\n\n"
    "<b>Служебное:</b>\n"
    "/profile - профиль карточек\n"
    "/skills_graph - Mermaid-граф навыков агента\n"
    "/subscribe - уведомления об изменении цен\n"
    "/unsubscribe - отписаться\n"
    "/help - это сообщение"
)


@dp.message(Command("start", "help"))
async def cmd_help(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer(HELP_TEXT, parse_mode="HTML")


@dp.message(Command("metrics"))
async def cmd_metrics(message: types.Message):
    if not await ensure_allowed(message):
        return
    limit = _message_command_limit(message.text, "metrics")
    rows = await db.get_recent_scrape_attempts(limit=limit)
    if not rows:
        return await message.answer("Метрик парсинга пока нет.")

    await message.answer(format_recent_scrape_attempts(rows), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("skill_note", "skill_lesson"))
async def cmd_skill_note(message: types.Message):
    if not await ensure_allowed(message):
        return
    command = "skill_lesson" if (message.text or "").startswith("/skill_lesson") else "skill_note"
    note = extract_command_payload(message.text or "", command)
    if not note:
        return await message.answer(
            f"Пришлите заметку после /{command}, например:\n"
            f"<code>/{command} router должен сохранять training prompt как одну задачу</code>",
            parse_mode="HTML",
        )
    proposal = create_skill_note_proposal(note, source=f"telegram:{message.from_user.id}")
    rel_path = proposal.path.relative_to(Path(__file__).resolve().parent.parent)
    await message.answer(
        "Создал pending skill proposal:\n"
        f"<code>{html.escape(str(rel_path))}</code>\n"
        f"proposed_id: <code>{html.escape(proposal.proposed_id)}</code>",
        parse_mode="HTML",
    )


@dp.message(Command("skill_pending"))
async def cmd_skill_pending(message: types.Message):
    if not await ensure_allowed(message):
        return
    paths = list_pending_skill_proposals(limit=10)
    if not paths:
        return await message.answer("Pending skill proposals пока нет.")
    root = Path(__file__).resolve().parent.parent
    lines = ["<b>Pending skill proposals:</b>"]
    for path in paths:
        try:
            label = str(path.relative_to(root))
        except ValueError:
            label = str(path)
        lines.append(f"- <code>{html.escape(label)}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("blocks"))
async def cmd_blocks(message: types.Message):
    if not await ensure_allowed(message):
        return
    limit = _message_command_limit(message.text, "blocks")
    rows = await db.get_recent_blocked_patterns(limit=limit)
    if not rows:
        return await message.answer("Block memory пока пустая.")

    await message.answer(format_blocked_patterns(rows), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("health"))
async def cmd_health(message: types.Message):
    if not await ensure_allowed(message):
        return

    items = []
    for marketplace in ("ozon", "wildberries", "yandex_market"):
        health = await db.get_marketplace_health(marketplace)
        decision = await db.recommend_scrape_strategy(marketplace)
        circuit_left = resilience.cooldown_remaining(marketplace)
        items.append({
            "marketplace": marketplace,
            "health": health,
            "decision": decision,
            "circuit_left": circuit_left,
        })
    await message.answer(format_marketplace_health(items), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    if not await ensure_allowed(message):
        return
    raw = (message.text or "").replace("/profile", "", 1).strip().lower()
    profiles = list_profiles()
    if not profiles:
        return await message.answer("❌ Профили не найдены в папке profiles.")

    if not raw:
        active = get_active_profile_name(message.chat.id)
        return await message.answer(
            f"Активный профиль: <b>{active}</b>\n"
            f"Доступные профили: {', '.join(profiles)}\n"
            "Чтобы переключить: <code>/profile имя</code>",
            parse_mode="HTML",
        )

    if raw not in profiles:
        return await message.answer(
            f"❌ Профиль <b>{raw}</b> не найден.\n"
            f"Доступно: {', '.join(profiles)}",
            parse_mode="HTML",
        )

    CHAT_PROFILES[message.chat.id] = raw
    profile = load_profile(raw)
    await message.answer(
        f"✅ Профиль переключен: <b>{raw}</b>\n"
        f"Язык: {profile.language}, стиль: {profile.tone_voice}, max_length: {profile.max_length}",
        parse_mode="HTML",
    )


# ── /add ──────────────────────────────────────────────────────────────────────
@dp.message(Command("skills_graph"))
async def cmd_skills_graph(message: types.Message):
    if not await ensure_allowed(message):
        return
    mermaid = task_planner.registry.graph.to_mermaid([
        "scraping.website",
        "market.search",
        "ozon.card.generate",
        "batch.cards",
    ])
    await message.answer(
        "<b>Skill graph</b>\n"
        "<pre><code class=\"language-mermaid\">"
        f"{html.escape(mermaid)}"
        "</code></pre>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    inline_urls = extract_supported_urls(extract_command_payload(message.text, "add"))
    if inline_urls:
        await state.clear()
        return await handle_natural_add_urls(message, inline_urls)
    await message.answer(
        "📎 Отправьте ссылки на товары Озон — каждую с новой строки:\n\n"
        "<code>https://www.ozon.ru/product/...</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_urls)


@dp.message(Form.waiting_urls)
async def handle_urls(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()

    urls = extract_supported_urls(message.text or "")
    if not urls:
        return await message.answer("❌ Ссылок не найдено.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(f"🚀 Запускаю парсинг {len(urls)} товаров...")

    proxy = PROXY if PROXY else None

    try:
        await worker_add_urls(db, urls, lambda t: notify_chat(message.chat.id, t), proxy=proxy)
        latest = await db.get_latest_product()
        if latest:
            await message.answer(
                "✅ Товар добавлен в мониторинг.\n"
                "Чтобы сразу собрать карточку товара, отправьте /make_card_last"
            )
    finally:
        parser_lock.release()


# ── /update ───────────────────────────────────────────────────────────────────
@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    async with db.session() as s:
        total = await s.scalar(select(func.count(Product.id)))
    if not total:
        return await message.answer("📭 База пустая. Добавьте товары через /add")

    await parser_lock.acquire()
    await message.answer(f"🔄 Обновляю цены {total} товаров...")

    proxy = PROXY if PROXY else None

    try:
        await worker_update_all(db, lambda t: notify_chat(message.chat.id, t), proxy=proxy)
        if await db.get_subscriber_count():
            await _broadcast_changes()
    finally:
        parser_lock.release()


# ── /search — поиск по названию ───────────────────────────────────────────────
@dp.message(Command("search"))
async def cmd_search(message: types.Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    inline_query = extract_command_payload(message.text, "search")
    if inline_query:
        await state.clear()
        return await run_search_query(message, state, inline_query, natural=False)
    await message.answer("🔍 Введите название товара для поиска на Озоне:")
    await state.set_state(Form.waiting_search)


async def run_search_query(message: types.Message, state: FSMContext, query: str, natural: bool) -> None:
    if not query:
        await message.answer("❌ Пустой запрос.")
        return
    funpay_urls = [url for url in extract_urls(query) if is_funpay_offer_url(url)]
    if funpay_urls:
        await handle_funpay_offer_search(message, funpay_urls[0])
        return
    is_valid, validation_error = validate_search_query(query)
    if not is_valid:
        await message.answer(f"⚠️ {validation_error}", parse_mode="HTML")
        return
    if parser_lock.locked():
        await message.answer("⚠️ Парсер занят.")
        return

    await parser_lock.acquire()
    try:
        prefix = "Понял запрос. " if natural else ""
        await message.answer(f"🔍 {prefix}Ищу на Озоне: <b>{query}</b>...", parse_mode="HTML")

        advice = await agent.search_advice(query)
        await message.answer(f"🤖 <b>Совет AI:</b>\n{advice}", parse_mode="HTML")

        results = await search_ozon(query, max_results=5)
        if not results:
            blocked_message = ozon_search_blocked_message()
            if blocked_message:
                await message.answer(
                    f"⚠️ {blocked_message}\n\n"
                    "Карточки всё равно можно собирать по вашим ТЗ или ссылкам: бот сделает черновики без конкурентной выдачи."
                )
                return
            await message.answer("😔 Ничего не найдено. Попробуйте другой запрос.")
            return

        lines = [f"🛍 <b>Найдено {len(results)} товаров:</b>\n"]
        for i, r in enumerate(results, 1):
            price_str = f"{r['price']} ₽" if r['price'] else "цена не определена"
            lines.append(
                f"{i}. <a href='{r['url']}'>{r['name'][:60]}</a>\n"
                f"   💰 {price_str}"
            )

        lines.append("\n💡 Отправьте /add и вставьте нужные ссылки чтобы добавить в мониторинг")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

        await state.set_state(Form.waiting_search_results)
        await state.update_data(search_results=results)
    except Exception as e:
        logger.exception("Ошибка поиска")
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        parser_lock.release()


@dp.message(Form.waiting_search)
async def handle_search(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()
    await run_search_query(message, state, (message.text or "").strip(), natural=False)


@dp.message(Form.waiting_search_results)
async def handle_search_add(message: types.Message, state: FSMContext):
    """Если пользователь написал номер(а) — добавляем соответствующие товары."""
    if not await ensure_allowed(message):
        await state.clear()
        return
    data = await state.get_data()
    results = data.get("search_results", [])
    await state.clear()

    # Пробуем распарсить номера
    if not message.text:
        return await message.answer("❌ Отправьте номер товара текстом, например: <code>1</code>", parse_mode="HTML")
    nums = [int(x.strip()) for x in message.text.replace(",", " ").split() if x.strip().isdigit()]
    urls = [results[n-1]["url"] for n in nums if 1 <= n <= len(results)]

    if urls:
        await message.answer(f"➕ Добавляю {len(urls)} товаров в мониторинг...")
        if parser_lock.locked():
            return await message.answer("⚠️ Парсер занят. Подождите.")
        await parser_lock.acquire()
        try:
            await worker_add_urls(db, urls, lambda t: notify_chat(message.chat.id, t))
        finally:
            parser_lock.release()
    else:
        # Не числа — обрабатываем как обычное сообщение
        await message.answer("Напишите /help чтобы увидеть доступные команды.")


# ── /analyze — AI анализ всего портфеля ──────────────────────────────────────
@dp.message(Command("ozon_card"))
async def cmd_ozon_card(message: types.Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    await message.answer(
        "Пришлите ТЗ на товар одним сообщением.\n\n"
        "Пример:\n"
        "<code>товар: Держатель телефона автомобильный\n"
        "бренд: Нет бренда\n"
        "категория: Автомобильные держатели\n"
        "цена: 599\n"
        "цвет: черный\n"
        "материал: ABS пластик\n"
        "вес: 180 г\n"
        "размер: 120x80x70 мм\n"
        "комплектация: держатель, крепление, коробка</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_ozon_card)


@dp.message(Command("ozon_batch_cards"))
async def cmd_ozon_batch_cards(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        return
    text = (message.text or "").replace("/ozon_batch_cards", "", 1).strip()
    if text:
        return await generate_ozon_batch_card_files(message, text)

    await message.answer(
        "Пришлите список товаров одним сообщением: по одному товару на строку.\n\n"
        "Можно смешивать ссылки и текстовые ТЗ:\n"
        "<code>https://www.ozon.ru/product/...\n"
        "кусачки маникюрные, цена 444, материал сталь\n"
        "кабель USB-C 1 м, цена 299, цвет черный</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_ozon_batch)


@dp.message(Command("card_research"))
async def cmd_card_research(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        return
    query = (message.text or "").replace("/card_research", "", 1).strip()
    if query:
        return await run_card_research(message, query)

    await message.answer(
        "🔎 Пришлите название товара для анализа конкурентов на Ozon.\n\n"
        "Например: <code>держатель телефона автомобильный</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_card_research)


@dp.message(Form.waiting_card_research)
async def handle_card_research_query(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()
    query = (message.text or "").strip()
    if not query:
        return await message.answer("❌ Пустой запрос.")
    await run_card_research(message, query)


async def run_card_research(message: types.Message, query: str):
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(f"🔎 Анализирую конкурентов на Ozon: <b>{query}</b>...", parse_mode="HTML")
    try:
        report = await build_card_research_message(query)
        await message.answer(report, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка анализа конкурентов для карточки")
        await message.answer(f"❌ Не удалось сделать анализ конкурентов: {e}")
    finally:
        parser_lock.release()


@dp.message(Command("make_card_last"))
async def cmd_make_card_last(message: types.Message):
    if not await ensure_allowed(message):
        return

    product = await db.get_latest_product()
    if not product:
        return await message.answer("📭 В базе пока нет товаров. Сначала добавьте товар через /add.")

    last_price = await db.get_last_price(product.id)
    task = _build_card_task_from_product(product, last_price.price if last_price else None)
    await message.answer(
        f"🧩 Собираю карточку по последнему товару:\n<b>{product.name[:80]}</b>",
        parse_mode="HTML",
    )
    await generate_ozon_card_files(message, task)


async def generate_ozon_card_files(message: types.Message, text: str):
    from app.card_filler import (
        build_ozon_card_search_query,
        build_ozon_card_draft,
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
            competitors = await search_ozon(search_query, max_results=8)
        except Exception as e:
            logger.warning(f"card competitor search failed: {e}")
            await message.answer("⚠️ Конкурентов сейчас не удалось собрать, продолжаю по данным товара.")
        finally:
            parser_lock.release()

    draft = await build_enhanced_ozon_card_draft(text, competitors=competitors, profile=profile)
    xlsx = export_ozon_card_xlsx(draft)
    json_buf = export_ozon_card_json(draft)
    await message.answer(format_ozon_card_preview(draft), parse_mode="HTML")
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


async def _read_text_document(document: types.Document) -> str:
    telegram_file = await bot.get_file(document.file_id)
    downloaded = await bot.download_file(telegram_file.file_path)
    if downloaded is None:
        return ""
    if hasattr(downloaded, "getvalue"):
        raw = downloaded.getvalue()
    else:
        raw = downloaded.read()
    return raw.decode("utf-8", errors="ignore")


async def generate_ozon_batch_card_files(message: types.Message, text: str):
    from app.card_filler import (
        OzonCardBatchItem,
        build_ozon_card_search_query,
        build_ozon_card_draft,
        build_enhanced_ozon_card_draft,
        export_ozon_cards_batch_json,
        export_ozon_cards_batch_xlsx,
        format_ozon_batch_preview,
    )

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
                    competitors = await search_ozon(build_ozon_card_search_query(base_draft), max_results=8)
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


@dp.message(Form.waiting_ozon_card)
async def handle_ozon_card_task(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()
    text = (message.text or "").strip()
    if not text:
        return await message.answer("Empty card task. Send product description as text.")

    try:
        await generate_ozon_card_files(message, text)
    except Exception as e:
        logger.exception("Ozon card generation error")
        await message.answer(f"Could not generate Ozon card: {e}")


@dp.message(Form.waiting_ozon_batch)
async def handle_ozon_batch_task(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()
    text = (message.text or "").strip()
    if not text:
        return await message.answer("❌ Пустой список. Пришлите ссылки или ТЗ, по одному товару на строку.")
    await generate_ozon_batch_card_files(message, text)


@dp.message(F.document)
async def handle_batch_card_file(message: types.Message):
    if not await ensure_allowed(message):
        return
    if not message.document:
        return

    caption = (message.caption or "").lower()
    file_name = (message.document.file_name or "").lower()
    if not (
        "/ozon_batch_cards" in caption
        or "/batch_cards" in caption
        or file_name.endswith(".txt")
        or file_name.endswith(".csv")
    ):
        return

    if not file_name.endswith(".txt") and not file_name.endswith(".csv"):
        return await message.answer("❌ Поддерживаются только .txt и .csv для пакетной сборки карточек.")

    text = await _read_text_document(message.document)
    if not text.strip():
        return await message.answer("❌ Файл пустой или не удалось прочитать текст.")

    await message.answer(
        "📦 Принял файл. Запускаю пакетную сборку карточек с активным профилем.\n"
        "Подсказка: переключить профиль можно командой /profile имя",
    )
    await generate_ozon_batch_card_files(message, text)


@dp.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("🤖 Анализирую все товары, секунду...")
    analysis = await agent.analyze_portfolio()
    await message.answer(f"🤖 <b>AI-анализ портфеля:</b>\n\n{analysis}", parse_mode="HTML")


# ── /deals — лучшие сделки ────────────────────────────────────────────────────
@dp.message(Command("deals"))
async def cmd_deals(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("💎 Ищу лучшие сделки...")
    deals = await agent.find_best_deals()

    if not deals:
        return await message.answer(
            "😔 Пока нет товаров на минимальной цене за 30 дней.\n"
            "Нужно больше данных — запустите /update через несколько дней."
        )

    lines = ["💎 <b>Лучшие сделки (минимум цены за 30 дней):</b>\n"]
    for d in deals:
        lines.append(
            f"🔥 <a href='{d['url']}'>{d['name'][:55]}</a>\n"
            f"   💰 {d['current_price']} ₽ (было {d['max_price']} ₽, "
            f"экономия {d['savings']} ₽ / {d['savings_pct']}%)\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ── /anomalies — подозрительные изменения ─────────────────────────────────────
@dp.message(Command("anomalies"))
async def cmd_anomalies(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("🔎 Анализирую изменения цен...")
    anomalies = await agent.detect_anomalies()

    if not anomalies:
        return await message.answer("✅ Подозрительных изменений цен не обнаружено.")

    lines = [f"⚠️ <b>Резкие изменения цен ({len(anomalies)} товаров):</b>\n"]
    for a in anomalies:
        lines.append(
            f"{a['direction']} <a href='{a['url']}'>{a['name'][:55]}</a>\n"
            f"   {a['old_price']} ₽ → {a['new_price']} ₽ ({a['change_pct']}%)\n"
        )

    # AI-комментарий
    if len(anomalies) > 0:
        names = ", ".join(a["name"][:30] for a in anomalies[:3])
        ai_comment = await agent._ask_claude(
            f"Резкие изменения цен на товары: {names}. "
            f"Дай краткий комментарий — это распродажа, накрутка или что-то другое? "
            f"Что посоветуешь покупателю?"
        )
        lines.append(f"\n🤖 <b>AI говорит:</b>\n{ai_comment}")

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ── /list ─────────────────────────────────────────────────────────────────────
@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    if not await ensure_allowed(message):
        return
    async with db.session() as s:
        products = (await s.execute(
            select(Product).order_by(Product.last_check.desc()).limit(20)
        )).scalars().all()

    if not products:
        return await message.answer("📭 База пустая. Добавьте товары через /add")

    lines = [f"📦 <b>Отслеживается {len(products)} товаров:</b>\n"]
    product_ids = [p.id for p in products]
    latest_at = (
        select(
            PriceHistory.product_id.label("product_id"),
            func.max(PriceHistory.recorded_at).label("recorded_at"),
        )
        .where(PriceHistory.product_id.in_(product_ids))
        .group_by(PriceHistory.product_id)
        .subquery()
    )
    async with db.session() as s:
        latest_rows = (await s.execute(
            select(PriceHistory)
            .join(
                latest_at,
                and_(
                    PriceHistory.product_id == latest_at.c.product_id,
                    PriceHistory.recorded_at == latest_at.c.recorded_at,
                ),
            )
        )).scalars().all()
    latest_by_product = {row.product_id: row for row in latest_rows}

    await message.answer(format_product_list(products, latest_by_product), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not await ensure_allowed(message):
        return
    async with db.session() as s:
        n_products = await s.scalar(select(func.count(Product.id)))
        n_history  = await s.scalar(select(func.count(PriceHistory.id)))
    subscribers = await db.get_subscribers()
    await message.answer(
        format_status_message(n_products, n_history, len(subscribers), agent._is_available()),
        parse_mode="HTML",
    )


@dp.message(Command("net_diag"))
async def cmd_net_diag(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("🔎 Проверяю сеть и прокси, подождите пару секунд...")

    dns_ok, dns_msg = await _probe_dns("api.telegram.org")
    tcp_ok, tcp_msg = await _probe_tcp("api.telegram.org", 443)
    https_ok, https_msg = await _probe_https("api.telegram.org")

    await message.answer(
        format_network_diagnostics(
            _mask_proxy_url(TELEGRAM_PROXY),
            _mask_proxy_url(PROXY),
            (dns_ok, dns_msg),
            (tcp_ok, tcp_msg),
            (https_ok, https_msg),
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    if not await ensure_allowed(message):
        return
    await db.add_subscriber(message.from_user.id)
    await message.answer("✅ Подписались на уведомления об изменении цен.")


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    if not await ensure_allowed(message):
        return
    await db.remove_subscriber(message.from_user.id)
    await message.answer("✅ Отписались от уведомлений.")


async def _broadcast_changes():
    try:
        two_h_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        async with db.session() as s:
            rows = (await s.execute(
                select(PriceHistory, Product)
                .join(Product)
                .where(PriceHistory.recorded_at >= two_h_ago)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(20)
            )).all()

        if not rows:
            return

        lines = ["📊 <b>Изменения цен:</b>"]
        for ph, p in rows:
            icon = "✅" if ph.availability_status == "in_stock" else "❌"
            lines.append(f"{icon} {p.name[:40]}: {ph.price} ₽")

        text = "\n".join(lines)
        subscribers = await db.get_subscribers()
        for uid in subscribers:
            try:
                if bot is None:
                    continue
                await bot.send_message(uid, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"broadcast error: {e}")


# ── Запуск ────────────────────────────────────────────────────────────────────
def _set_active_bot(active_bot: Bot | None) -> None:
    global bot
    bot = active_bot


_telegram_reconnect_delay = telegram_reconnect_delay


async def start_bot() -> bool:
    return await run_telegram_polling(
        db=db,
        dp=dp,
        commands=TELEGRAM_COMMANDS,
        set_active_bot=_set_active_bot,
    )

async def _start_bot_once() -> bool:
    return await start_bot()


# ── /wb — добавить товар с Wildberries ────────────────────────────────────────
@dp.message(Command("wb"))
async def cmd_wb(message: types.Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    await message.answer(
        "🟣 Отправьте ссылку(и) на товары <b>Wildberries</b>:\n\n"
        "<code>https://www.wildberries.ru/catalog/...</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_urls)


@dp.message(Command("wb_deals"))
async def cmd_wb_deals(message: types.Message):
    if not await ensure_allowed(message):
        return
    query = (message.text or "").replace("/wb_deals", "", 1).strip()
    if not query:
        return await message.answer(
            "🟣 Укажите запрос для Wildberries, например:\n"
            "<code>/wb_deals игровое кресло</code>",
            parse_mode="HTML",
        )
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(f"🟣 Ищу распродажи WB: <b>{html.escape(query)}</b>...", parse_mode="HTML")
    try:
        from app.parsers.wildberries import WildberriesParser
        from app.wb_deals import find_wb_deals

        results = await WildberriesParser().search(query, max_results=80)
        deals = find_wb_deals(results, min_discount_pct=30, limit=15)
        if not deals:
            return await message.answer(
                "😔 По этому запросу не нашёл скидок от 30%.\n"
                "Попробуйте другой запрос или проверьте позже."
            )

        lines = [f"🔥 <b>Найдено скидок WB: {len(deals)}</b>\n"]
        for idx, deal in enumerate(deals, 1):
            stock = "✅" if deal["availability"] == "in_stock" else "❌"
            lines.append(
                f"{idx}. {stock} <a href='{deal['url']}'>{html.escape(deal['name'][:70])}</a>\n"
                f"   💰 <b>{deal['price']} ₽</b> (было {deal['old_price']} ₽, -{deal['discount_pct']}%)"
            )
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка поиска распродаж WB")
        await message.answer(f"❌ Ошибка поиска распродаж WB: {e}")
    finally:
        parser_lock.release()


# ── /compare — сравнить цены между маркетплейсами ─────────────────────────────
@dp.message(Command("compare"))
async def cmd_compare(message: types.Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    await message.answer(
        "🔍 Отправьте название товара для сравнения цен на Озоне и WB:\n"
        "Например: <code>iPhone 15 128GB</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_compare)


@dp.message(Form.waiting_compare)
async def handle_compare(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()
    if not message.text:
        return await message.answer("❌ Отправьте запрос текстом.")
    query = message.text.strip()
    if not query:
        return await message.answer("❌ Пустой запрос.")

    await message.answer(f"🔎 Сравниваю цены: <b>{query}</b>...", parse_mode="HTML")
    try:
        from app.parsers.wildberries import WildberriesParser

        ozon_results = await search_ozon(query, max_results=1)
        wb_results = await WildberriesParser().search(query, max_results=1)

        ozon_price = ozon_results[0].get("price") if ozon_results else None
        wb_price = wb_results[0].price if wb_results else None
        product_name = (
            ozon_results[0].get("name")
            if ozon_results
            else wb_results[0].name if wb_results else query
        )

        if not ozon_results and not wb_results:
            return await message.answer("😔 Ничего не найдено. Попробуйте другой запрос.")

        lines = []
        if ozon_results:
            r = ozon_results[0]
            price = f"{r.get('price')} ₽" if r.get("price") else "цена не определена"
            lines.append(f"🔵 <a href='{r['url']}'>Ozon</a>: <b>{price}</b>")
        if wb_results:
            r = wb_results[0]
            price = f"{r.price} ₽" if r.price else "цена не определена"
            lines.append(f"🟣 <a href='{r.url}'>Wildberries</a>: <b>{price}</b>")

        advice = await agent.compare_prices(product_name, ozon_price, wb_price)
        await message.answer(
            "\n".join(lines) + f"\n\n{advice}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Ошибка сравнения цен")
        await message.answer(f"❌ Ошибка сравнения: {e}")


# ── /reviews — анализ отзывов конкретного товара ──────────────────────────────
@dp.message(Command("reviews"))
async def cmd_reviews(message: types.Message, state: FSMContext):
    """Анализирует отзывы последнего добавленного WB-товара."""
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    async with db.session() as s:
        from sqlalchemy import select
        products = (await s.execute(
            select(Product)
            .where(Product.url.contains("wildberries"))
            .order_by(Product.last_check.desc())
            .limit(5)
        )).scalars().all()

    if not products:
        return await message.answer(
            "📭 Нет товаров с Wildberries.\n"
            "Добавьте через /wb — WB отдаёт отзывы через API."
        )

    lines = ["Выберите товар для анализа отзывов (ответьте номером):\n"]
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {p.name[:50]}")
    lines.append("\nНапример: <code>1</code>")

    await state.set_state(Form.waiting_reviews)
    await state.update_data(review_product_ids=[p.id for p in products])
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Form.waiting_reviews)
async def handle_reviews_choice(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()

    try:
        if not message.text:
            raise ValueError
        choice = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Отправьте номер товара, например: <code>1</code>", parse_mode="HTML")

    product_ids = data.get("review_product_ids", [])
    if not (1 <= choice <= len(product_ids)):
        return await message.answer("❌ Нет такого номера в списке.")

    async with db.session() as s:
        product = await s.get(Product, product_ids[choice - 1])
    if not product:
        return await message.answer("❌ Товар не найден.")

    await message.answer(f"🧠 Загружаю и анализирую отзывы: <b>{product.name[:60]}</b>...", parse_mode="HTML")
    try:
        import aiohttp
        from app.parsers.wildberries import WildberriesParser, _extract_wb_id

        nm_id = _extract_wb_id(product.url)
        if not nm_id:
            return await message.answer("❌ Не удалось определить ID товара Wildberries.")

        parser = WildberriesParser()
        async with aiohttp.ClientSession() as session:
            reviews = await parser._fetch_reviews(session, nm_id)

        result = await agent.analyze_reviews(reviews, product.name or product.url)
        await message.answer(result, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка анализа отзывов")
        await message.answer(f"❌ Ошибка анализа отзывов: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ЭКСПОРТ
# ═══════════════════════════════════════════════════════════════════════════════

@dp.message(Command("export_csv"))
async def cmd_export_csv(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Preparing CSV file...")
    try:
        await send_price_export(bot, db, message.chat.id, "csv")
    except Exception as e:
        await message.answer(f"Export error: {e}")


@dp.message(Command("export_excel"))
async def cmd_export_excel(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Preparing Excel file...")
    try:
        await send_price_export(bot, db, message.chat.id, "excel")
    except Exception as e:
        await message.answer(f"Export error: {e}")


@dp.message(Command("deep_analyze"))
async def cmd_deep_analyze(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Starting deep AI market analysis...")
    result = await build_market_overview_message(db)
    await message.answer(result, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("forecast"))
async def cmd_forecast(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Calculating price forecast...")
    result = await build_price_forecast_message(db)
    await message.answer(result, parse_mode="HTML")


@dp.message(Command("alerts"))
async def cmd_alerts(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Checking active alerts...")
    result = await build_price_alerts_message(db)
    await message.answer(result, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Generating HTML report...")
    try:
        await send_html_report(bot, db, message.chat.id)
    except Exception as e:
        logger.exception("HTML report generation error")
        await message.answer(f"Report error: {e}")


async def handle_natural_add_urls(message: types.Message, urls: list[str]):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(f"🚀 Нашёл ссылку(и), запускаю парсинг {len(urls)} товар(ов)...")
    proxy = PROXY if PROXY else None
    try:
        await worker_add_urls(db, urls, lambda t: notify_chat(message.chat.id, t), proxy=proxy)
    finally:
        parser_lock.release()


async def handle_natural_card_urls(message: types.Message, urls: list[str]):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer(f"🚀 Нашёл ссылку для карточки, сначала получаю данные товара...")
    proxy = PROXY if PROXY else None
    try:
        await worker_add_urls(db, urls[:1], lambda t: notify_chat(message.chat.id, t), proxy=proxy)
    finally:
        parser_lock.release()

    product = await db.get_product_by_hash(url_to_hash(urls[0]))
    if not product:
        return await message.answer(
            "⚠️ Товар по ссылке не удалось сохранить в базу. Пришлите ТЗ текстом или попробуйте ссылку ещё раз."
        )

    last_price = await db.get_last_price(product.id)
    task = _build_card_task_from_product(product, last_price.price if last_price else None)
    await message.answer(
        f"🧩 Данные получил, собираю карточку:\n<b>{(product.name or 'товар')[:80]}</b>",
        parse_mode="HTML",
    )
    await generate_ozon_card_files(message, task)


async def handle_natural_search(message: types.Message, query: str):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    is_valid, validation_error = validate_search_query(query)
    if not is_valid:
        return await message.answer(f"⚠️ {validation_error}", parse_mode="HTML")

    await parser_lock.acquire()
    await message.answer(f"🔍 Понял запрос. Ищу на Озоне: <b>{query}</b>...", parse_mode="HTML")
    try:
        results = await search_ozon(query, max_results=5)
        if not results:
            blocked_message = ozon_search_blocked_message()
            if blocked_message:
                return await message.answer(
                    f"⚠️ {blocked_message}\n\n"
                    "Карточки всё равно можно собирать по вашим ТЗ или ссылкам: бот сделает черновики без конкурентной выдачи."
                )
            return await message.answer("😔 Ничего не найдено. Попробуйте другой запрос.")

        lines = [f"🛍 <b>Найдено {len(results)} товаров:</b>\n"]
        for i, r in enumerate(results, 1):
            price_str = f"{r['price']} ₽" if r.get("price") else "цена не определена"
            lines.append(
                f"{i}. <a href='{r['url']}'>{r['name'][:60]}</a>\n"
                f"   💰 {price_str}"
            )

        lines.append("\n💡 Чтобы добавить товар в мониторинг, просто пришлите его ссылку.")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка свободного поиска")
        await message.answer(f"❌ Ошибка поиска: {e}")
    finally:
        parser_lock.release()


async def dispatch_natural_intent(message: types.Message, state: FSMContext, intent: str, payload) -> bool:
    if intent == "repair_task":
        await handle_repair_task(message, payload)
        return True
    if intent == "scraping_task":
        await handle_scraping_task(message, payload)
        return True
    if intent == "page_classification_training":
        if isinstance(payload, StructuredTask) and payload.target_url:
            await message.answer(
                await classify_page_before_parsing(payload.target_url),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        await message.answer(
            "Принял 1 задачу.\n\n"
            "Намерение: page_classification_training\n"
            "Действие: classify_page_before_parsing\n"
            "Статус: нужен URL страницы для анализа"
        )
        return True
    if intent == "add_urls":
        await handle_natural_add_urls(message, payload)
        return True
    if intent == "ozon_card_urls":
        await handle_natural_card_urls(message, payload)
        return True
    if intent == "ozon_batch_cards":
        await generate_ozon_batch_card_files(message, payload)
        return True
    if intent == "ozon_batch_prompt":
        await cmd_ozon_batch_cards(message, state)
        return True
    if intent == "update":
        await cmd_update(message)
        return True
    if intent == "list":
        await cmd_list(message)
        return True
    if intent == "status":
        await cmd_status(message)
        return True
    if intent == "make_card_last":
        await cmd_make_card_last(message)
        return True
    if intent == "ozon_card":
        await generate_ozon_card_files(message, payload)
        return True
    if intent == "ozon_card_prompt":
        await cmd_ozon_card(message, state)
        return True
    if intent == "card_research":
        await run_card_research(message, payload)
        return True
    if intent == "search":
        await handle_natural_search(message, payload)
        return True
    return False


@dp.message()
async def handle_unhandled_message(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        return
    if not message.text:
        return
    text = message.text.strip()
    urls = extract_urls(text)
    funpay_urls = [url for url in urls if is_funpay_offer_url(url)]
    if funpay_urls:
        if not allowed(message.from_user.id):
            return await message.answer("⛔ Доступ запрещён.")
        return await handle_funpay_offer_search(message, funpay_urls[0])

    context = get_chat_context(message.chat.id)
    urls = extract_urls(text)
    if context.should_continue_page_classification(urls, text):
        context.clear_active()
        return await message.answer(
            await classify_page_before_parsing(urls[0]),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    intent, payload = parse_natural_request(text, context=context)
    if intent == "repair_task":
        return await dispatch_natural_intent(message, state, intent, payload)
    if intent == "scraping_task":
        return await dispatch_natural_intent(message, state, intent, payload)
    if intent == "page_classification_training":
        return await dispatch_natural_intent(message, state, intent, payload)
    if intent == "ozon_batch_cards":
        return await dispatch_natural_intent(message, state, intent, payload)

    tasks = split_natural_tasks(text)
    if len(tasks) > 1:
        if len(tasks) > MAX_NATURAL_TASKS:
            return await message.answer(
                f"⚠️ В одном сообщении могу разобрать до {MAX_NATURAL_TASKS} задач. "
                "Разбейте список на несколько сообщений."
            )

        card_sources, other_tasks = _split_card_and_other_tasks(tasks)
        if len(card_sources) > 1:
            await message.answer(
                f"Принял карточных заданий: <b>{len(card_sources)}</b>. "
                "Сверну их в один пакетный XLSX/JSON.",
                parse_mode="HTML",
            )
            await generate_ozon_batch_card_files(message, "\n".join(card_sources))
            if not other_tasks:
                return
            tasks = other_tasks

        await message.answer(f"Принял задач: <b>{len(tasks)}</b>. Выполню по очереди.", parse_mode="HTML")
        for index, task in enumerate(tasks, 1):
            intent, payload = parse_natural_request(task, context=context)
            if intent == "unknown":
                await message.answer(f"⚠️ Задача {index}: не понял «{task[:80]}».")
                continue
            await message.answer(f"▶️ Задача {index}/{len(tasks)}: <code>{task[:120]}</code>", parse_mode="HTML")
            handled = await dispatch_natural_intent(message, state, intent, payload)
            if not handled:
                response = build_unhandled_message_response(task)
                if response:
                    await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
        return

    if await dispatch_natural_intent(message, state, intent, payload):
        return

    response = build_unhandled_message_response(text)
    if response:
        await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
