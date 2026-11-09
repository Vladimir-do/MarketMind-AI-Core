# @skills: telegram-aiogram-fsm, telegram-natural-intent-router, telegram-batch-card-files, cross-marketplace-search
import asyncio
import html
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from app.agent import PriceAgent
from app.card_profiles import list_profiles, load_profile
from app.config import ADMIN_IDS, PROXY, TELEGRAM_PROXY, logger
from app.database import Database, url_to_hash
from app.parsers.funpay import (
    build_funpay_search_query,
    fetch_funpay_offer,
    format_funpay_offer_summary,
    is_funpay_offer_url,
)
from app.parsers.router import search_all_marketplaces
from app.parsers.wildberries import WildberriesParser
from app.resilience import resilience
from app.searcher import ozon_search_blocked_message, search_ozon
from app.skill_notes import create_skill_note_proposal, list_pending_skill_proposals
from app.task_intents import (
    ContextSession,
    StructuredTask,
    TaskType,
    detect_task_intent,
)
from app.task_planner import TaskPlanner
from app.telegram_ai_reports import (
    build_market_overview_message,
    build_price_alerts_message,
    build_price_forecast_message,
)

# Backward-compatible helper re-exports used by tests and older callers.
from app.telegram_card_handlers import (
    _build_card_task_from_product_data,
    _read_text_document,
    _split_batch_card_sources,  # noqa: F401
    generate_ozon_batch_card_files,
    generate_ozon_card_files,
)
from app.telegram_card_research import build_card_research_message
from app.telegram_card_tasks import (
    build_card_task_from_product as _build_card_task_from_product,
)
from app.telegram_card_tasks import build_card_task_from_url as _build_card_task_from_url  # noqa: F401
from app.telegram_conversation import (
    _conversation_response,
    _is_conversation,
)
from app.telegram_diagnostics import (
    probe_dns as _probe_dns,
)
from app.telegram_diagnostics import (
    probe_https as _probe_https,
)
from app.telegram_diagnostics import (
    probe_tcp as _probe_tcp,
)
from app.telegram_exports import send_html_report, send_price_export
from app.telegram_humanize import (
    access_denied as _h_access,
)
from app.telegram_humanize import (
    analyzing as _h_analyzing,
)
from app.telegram_humanize import (
    empty_database as _h_empty_db,
)
from app.telegram_humanize import (
    help_text as _h_help,
)
from app.telegram_humanize import (
    network_check as _h_network,
)
from app.telegram_humanize import (
    no_blocks as _h_no_blocks,
)
from app.telegram_humanize import (
    no_metrics as _h_no_metrics,
)
from app.telegram_humanize import (
    parser_busy as _h_busy,
)
from app.telegram_humanize import (
    report_generating as _h_report,
)
from app.telegram_humanize import (
    search_started as _h_search_start,
)
from app.telegram_humanize import (
    subscribe_ok as _h_sub_ok,
)
from app.telegram_humanize import (
    unsubscribe_ok as _h_unsub_ok,
)
from app.telegram_humanize import (
    update_started as _h_update_start,
)
from app.telegram_marketplace_utils import (
    _first_marketplace_product,
    _format_cross_marketplace_results,
    _marketplace_result_count,
)
from app.telegram_messages import (
    command_limit as _message_command_limit,
)
from app.telegram_messages import (
    format_blocked_patterns,
    format_marketplace_health,
    format_network_diagnostics,
    format_product_list,
    format_recent_scrape_attempts,
    format_status_message,
)
from app.telegram_read_service import TelegramReadService
from app.telegram_runtime import run_telegram_polling, telegram_reconnect_delay
from app.telegram_scraping import (  # noqa: F401
    build_repair_diagnostic_report,
    build_scraping_preflight_decision,
    classify_page_before_parsing,
    fetch_html,
    format_scraping_preflight_decision,
    format_structured_task_plan,
    handle_repair_task,
    handle_scraping_task,
)
from app.telegram_text_utils import (
    _build_card_task_from_combined_request,
    _clean_marketplace_search_query,
    _clean_natural_payload,
    _clean_product_search_query,
    _collect_batch_card_sources_from_tasks,  # noqa: F401
    _extract_wildberries_card_search_query,
    _is_meta_task_instruction,
    _is_training_protocol_fragment,
    _is_vague_product_reference,
    _mentions_card,
    _mentions_wildberries,
    _split_card_and_other_tasks,
    split_natural_tasks,
)
from app.telegram_url_utils import (
    extract_command_payload,
    extract_supported_urls,
    extract_urls,
    is_supported_marketplace_url,
    validate_search_query,
)
from app.utils.proxy import mask_proxy_url as _mask_proxy_url
from app.utils.urls import is_yandex_market_url
from app.worker import worker_add_urls, worker_update_all

# ── Бот ───────────────────────────────────────────────────────────────────────
bot: Bot | None = None
dp = Dispatcher(storage=MemoryStorage())


@dp.errors()
async def handle_unhandled_error(event: types.ErrorEvent) -> bool:
    """Last-resort safety net: without this, aiogram's own dispatcher loop
    swallows any exception a handler doesn't catch itself (logs it, sends
    nothing to the user — see loggers.event.exception in aiogram's
    Dispatcher._process_update). The user is left with no response at all,
    looking as if the bot ignored the command."""
    logger.error(
        "Unhandled exception in Telegram handler: %r", event.exception, exc_info=event.exception
    )
    message = getattr(event.update, "message", None)
    if message is not None:
        try:
            await message.answer("⚠️ Произошла ошибка при обработке команды. Попробуйте ещё раз позже.")
        except Exception as e:
            logger.error(f"failed to notify user about handler error: {e}")
    return True


db = Database()
agent = PriceAgent(db)
telegram_read_service = TelegramReadService(db)
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
    return bool(ADMIN_IDS) and user_id in ADMIN_IDS


async def ensure_allowed(message: types.Message) -> bool:
    if allowed(message.from_user.id):
        return True
    await message.answer(_h_access())
    return False


def get_active_profile_name(chat_id: int) -> str:
    return CHAT_PROFILES.get(chat_id, DEFAULT_PROFILE_NAME)


def get_active_profile(chat_id: int) -> dict:
    profile = load_profile(get_active_profile_name(chat_id))
    return profile.as_dict()


_MAX_CHAT_CONTEXTS = 1000


def get_chat_context(chat_id: int) -> ContextSession:
    if len(CHAT_CONTEXTS) > _MAX_CHAT_CONTEXTS:
        keys_to_remove = list(CHAT_CONTEXTS.keys())[:200]
        for k in keys_to_remove:
            del CHAT_CONTEXTS[k]
    context = CHAT_CONTEXTS.get(chat_id)
    if context is None:
        context = ContextSession()
        CHAT_CONTEXTS[chat_id] = context
    return context


# Scraping functions extracted to app.telegram_scraping



# Conversation patterns imported from app.telegram_conversation


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
    # Explicit product briefs should always enter card generation, never
    # marketplace search (e.g. "товар: Беспроводные наушники").
    if re.search(r"(?im)^\s*(?:товар|название товара|product(?: name)?)\s*[:=]\s*\S+", raw):
        return "ozon_card", raw
    structured_task = detect_task_intent(raw, context=context)
    if structured_task.type is TaskType.REPAIR:
        return "repair_task", structured_task
    if structured_task.type is TaskType.SCRAPING:
        return "scraping_task", structured_task
    if structured_task.type is TaskType.PAGE_CLASSIFICATION_TRAINING:
        return "page_classification_training", structured_task

    low = raw.lower()
    urls = extract_supported_urls(raw)

    if _is_meta_task_instruction(raw) and not urls:
        return "task_instruction", raw

    if re.search(r"\b(обнови|обновить|проверь|проверить|перепроверь)\b", low) and re.search(r"\b(цен|цены|товар|товары|прайс)\b", low):
        return "update", None

    if re.search(r"\b(список|покажи товары|что отслеж|отслеживаем)\b", low):
        return "list", None

    if re.search(r"\b(статус|сколько товаров|состояние базы|база)\b", low):
        return "status", None

    if _mentions_card(low):
        if _mentions_wildberries(raw):
            wb_query = _extract_wildberries_card_search_query(raw)
            if wb_query:
                return "wildberries_card_search", wb_query

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
                if _mentions_wildberries(query):
                    wb_query = _clean_marketplace_search_query(query)
                    if not wb_query and context and context.last_marketplace_query:
                        wb_query = context.last_marketplace_query
                    if wb_query:
                        return "wildberries_search", wb_query
                return "search", _clean_product_search_query(query)

    if _is_conversation(raw):
        return "conversation", raw

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
    marketplace_pages = []
    for url in urls:
        host = (urlparse(url).netloc or "").lower()
        if "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(url):
            if is_supported_marketplace_url(url):
                supported_urls.append(url)
            else:
                marketplace_pages.append(host or "marketplace")
        else:
            unsupported_hosts.append(host or "unknown")

    if unsupported_hosts:
        host_list = ", ".join(sorted(set(unsupported_hosts)))
        return (
            f"Ссылка с сайта <b>{html.escape(host_list)}</b> пока не поддерживается.\n\n"
            "Сейчас я умею добавлять товары по ссылкам Ozon/Wildberries через /add "
            "и искать на Ozon по названию через /search.\n"
            "Пришлите название товара, например: <code>держатель для телефона</code>."
        )

    if marketplace_pages:
        host_list = ", ".join(sorted(set(marketplace_pages)))
        return (
            f"Это страница маркетплейса <b>{html.escape(host_list)}</b>, а не карточка товара.\n\n"
            "Пришлите ссылку на конкретный товар, например "
            "<code>https://www.wildberries.ru/catalog/123456789/detail.aspx</code>, "
            "или обычное название товара для поиска."
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
                f"{i}. <a href='{html.escape(str(result['url']), quote=True)}'>{html.escape(str(result['name'])[:60])}</a>\n"
                f"   💰 {html.escape(str(price_str))}"
            )
        lines.append("\n💡 Чтобы добавить найденный товар в мониторинг, используйте /add и ссылку Ozon.")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        logger.exception("Ошибка обработки FunPay-ссылки")
        await message.answer("❌ Не удалось разобрать FunPay-ссылку. Попробуйте позже.")
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
    await message.answer(_h_help(), parse_mode="HTML")


@dp.message(Command("metrics"))
async def cmd_metrics(message: types.Message):
    if not await ensure_allowed(message):
        return
    limit = _message_command_limit(message.text, "metrics")
    rows = await db.get_recent_scrape_attempts(limit=limit)
    if not rows:
        return await message.answer(_h_no_metrics())

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
        return await message.answer(_h_no_blocks())

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
            f"Активный профиль: <b>{html.escape(str(active))}</b>\n"
            f"Доступные профили: {html.escape(', '.join(profiles))}\n"
            "Чтобы переключить: <code>/profile имя</code>",
            parse_mode="HTML",
        )

    if raw not in profiles:
        return await message.answer(
            f"❌ Профиль <b>{html.escape(raw)}</b> не найден.\n"
            f"Доступно: {html.escape(', '.join(profiles))}",
            parse_mode="HTML",
        )

    CHAT_PROFILES[message.chat.id] = raw
    profile = load_profile(raw)
    await message.answer(
        f"✅ Профиль переключен: <b>{html.escape(raw)}</b>\n"
        f"Язык: {html.escape(str(profile.language))}, стиль: {html.escape(str(profile.tone_voice))}, max_length: {profile.max_length}",
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
        return await message.answer(_h_access())
    inline_urls = extract_supported_urls(extract_command_payload(message.text, "add"))
    if inline_urls:
        await state.clear()
        return await handle_natural_add_urls(message, inline_urls)
    await message.answer(
        "Отправьте ссылки на товары — каждую с новой строки.\n\n"
        "Поддерживаю Ozon, Wildberries, Yandex Market и FunPay.\n\n"
        "<code>https://www.ozon.ru/product/...</code>\n"
        "<code>https://www.wildberries.ru/catalog/...</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_urls)


async def _auto_generate_blocked_ozon_cards(message: types.Message, urls: list[str]) -> int:
    """Automatically create a card draft for Ozon URLs without confirmed product-page data."""
    generated = 0
    for url in urls:
        host = (urlparse(url).netloc or "").lower()
        if "ozon.ru" not in host:
            continue
        product = await db.get_product_by_hash(url_to_hash(url))
        if not product:
            continue
        last_price = await db.get_last_price(product.id)
        if not last_price or (last_price.availability_status or "").lower() not in {"blocked", "draft"}:
            continue

        task = _build_card_task_from_product(product, last_price.price if last_price else None)
        task += (
            "\nВАЖНО: исходная карточка Ozon заблокировала парсинг. "
            "Название из URL не подтверждено страницей товара. Не придумывай цену, фотографии, "
            "бренд, состав, дозировки, характеристики, наличие или отзывы. "
            "Явно пометь отсутствующие сведения как требующие проверки."
        )
        await message.answer(
            "🤖 Ozon не отдал карточку товара. Не останавливаюсь — автоматически создаю "
            "проверочный AI-черновик по доступным данным."
        )
        try:
            await generate_ozon_card_files(
                message,
                task,
                parser_lock=parser_lock,
                bot=bot,
                get_active_profile=get_active_profile,
            )
            generated += 1
        except Exception:
            logger.exception("Automatic card generation failed for provisional Ozon URL: %s", url)
            await message.answer(
                "⚠️ Черновик товара сохранён, но автоматически сформировать файлы не удалось. "
                "Можно повторить через /make_card_last."
            )
    return generated


@dp.message(Form.waiting_urls)
async def handle_urls(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        await state.clear()
        return
    await state.clear()

    urls = extract_supported_urls(message.text or "")
    if not urls:
        return await message.answer("Не нашёл ссылок в сообщении. Отправьте ссылки на товары Ozon/WB/Yandex.")
    if parser_lock.locked():
        return await message.answer(_h_busy())

    await parser_lock.acquire()
    await message.answer(f"🚀 Запускаю парсинг {len(urls)} товаров...")

    proxy = PROXY if PROXY else None

    try:
        await worker_add_urls(db, urls, lambda t: notify_chat(message.chat.id, t), proxy=proxy)
    finally:
        parser_lock.release()

    auto_cards = await _auto_generate_blocked_ozon_cards(message, urls)
    if not auto_cards:
        latest = await db.get_latest_product()
        if latest:
            await message.answer(
                "✅ Товар добавлен в мониторинг.\n"
                "Чтобы сразу собрать карточку товара, отправьте /make_card_last"
            )


# ── /update ───────────────────────────────────────────────────────────────────
@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    if not allowed(message.from_user.id):
        return await message.answer(_h_access())
    if parser_lock.locked():
        return await message.answer(_h_busy())

    total = await telegram_read_service.get_product_count()
    if not total:
        return await message.answer(_h_empty_db())

    await parser_lock.acquire()
    await message.answer(_h_update_start(total))

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
        return await message.answer(_h_access())
    inline_query = extract_command_payload(message.text, "search")
    if inline_query:
        await state.clear()
        return await run_search_query(message, state, inline_query, natural=False)
    await message.answer("Введите название товара, который ищете на Ozon:")
    await state.set_state(Form.waiting_search)


async def run_search_query(message: types.Message, state: FSMContext, query: str, natural: bool) -> None:
    if not query:
        await message.answer("Пустой запрос. Напишите что искать.")
        return
    funpay_urls = [url for url in extract_urls(query) if is_funpay_offer_url(url)]
    if funpay_urls:
        await handle_funpay_offer_search(message, funpay_urls[0])
        return
    is_valid, validation_error = validate_search_query(query)
    if not is_valid:
        await message.answer(html.escape(str(validation_error)), parse_mode="HTML")
        return
    if parser_lock.locked():
        await message.answer(_h_busy())
        return

    await parser_lock.acquire()
    try:
        prefix = "Понял. " if natural else ""
        await message.answer(html.escape(f"{prefix}{_h_search_start(query)}"), parse_mode="HTML")

        advice = await agent.search_advice(query)
        await message.answer(f"🤖 <b>Совет AI:</b>\n{html.escape(str(advice))}", parse_mode="HTML")

        results = await search_ozon(query, max_results=5)
        if not results:
            blocked_message = ozon_search_blocked_message()
            await message.answer(
                "🔁 На Ozon сейчас пусто или поиск недоступен. Сразу проверяю другие маркетплейсы..."
            )
            all_results = await search_all_marketplaces(
                query,
                max_per_site=5,
                exclude_marketplaces=("ozon",) if blocked_message else (),
            )
            if _marketplace_result_count(all_results):
                await message.answer(
                    _format_cross_marketplace_results(
                        all_results,
                        title=f"Нашёл варианты по запросу: {query}",
                        empty_message="",
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return
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
                f"{i}. <a href='{html.escape(str(r['url']), quote=True)}'>{html.escape(str(r['name'])[:60])}</a>\n"
                f"   💰 {html.escape(str(price_str))}"
            )

        lines.append("\n💡 Отправьте /add и вставьте нужные ссылки чтобы добавить в мониторинг")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

        await state.set_state(Form.waiting_search_results)
        await state.update_data(search_results=results)
    except Exception:
        logger.exception("Ошибка поиска")
        await message.answer("❌ Ошибка поиска. Попробуйте позже.")
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
        return await message.answer(_h_access())
    await message.answer(
        "Отправьте описание товара одним сообщением.\n\n"
        "Можно просто текстом, например:\n"
        "<i>«Держатель телефона автомобильный, черный, ABS пластик, 180г»</i>\n\n"
        "Или подробно:\n"
        "<code>товар: Держатель телефона автомобильный\n"
        "бренд: Нет бренда\n"
        "категория: Автомобильные держатели\n"
        "цена: 599\n"
        "цвет: черный\n"
        "материал: ABS пластик\n"
        "вес: 180 г</code>",
        parse_mode="HTML",
    )
    await state.set_state(Form.waiting_ozon_card)


@dp.message(Command("ozon_batch_cards"))
async def cmd_ozon_batch_cards(message: types.Message, state: FSMContext):
    if not await ensure_allowed(message):
        return
    text = (message.text or "").replace("/ozon_batch_cards", "", 1).strip()
    if text:
        return await generate_ozon_batch_card_files(
            message, text, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile, db=db,
        )

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
    await message.answer(f"🔎 Анализирую конкурентов на Ozon: <b>{html.escape(query)}</b>...", parse_mode="HTML")
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
        f"🧩 Собираю карточку по последнему товару:\n<b>{html.escape(str(product.name or 'товар')[:80])}</b>",
        parse_mode="HTML",
    )
    await generate_ozon_card_files(message, task, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile)


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
        await generate_ozon_card_files(message, text, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile)
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
    try:
        await generate_ozon_batch_card_files(
            message, text, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile, db=db,
        )
    except Exception as e:
        logger.error("Batch card generation failed: %s", e)
        await message.answer(f"❌ Ошибка при генерации пачки карточек: {e}")


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

    text = await _read_text_document(message.document, bot=bot)
    if not text.strip():
        return await message.answer("❌ Файл пустой или не удалось прочитать текст.")

    await message.answer(
        "📦 Принял файл. Запускаю пакетную сборку карточек с активным профилем.\n"
        "Подсказка: переключить профиль можно командой /profile имя",
    )
    await generate_ozon_batch_card_files(
        message, text, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile, db=db,
    )


@dp.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer(_h_analyzing())
    analysis = await agent.analyze_portfolio()
    await message.answer(f"<b>AI-анализ портфеля:</b>\n\n{html.escape(analysis)}", parse_mode="HTML")


# ── /deals — лучшие сделки ────────────────────────────────────────────────────
@dp.message(Command("deals"))
async def cmd_deals(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Ищу лучшие сделки...")
    deals = await agent.find_best_deals()

    if not deals:
        return await message.answer(
            "Пока нет товаров на минимальной цене за 30 дней.\n"
            "Нужно больше данных — запустите /update через несколько дней."
        )

    lines = ["💎 <b>Лучшие сделки (минимум цены за 30 дней):</b>\n"]
    for d in deals:
        lines.append(
            f"🔥 <a href='{html.escape(str(d['url']), quote=True)}'>{html.escape(str(d['name'])[:55])}</a>\n"
            f"   💰 {html.escape(str(d['current_price']))} ₽ (было {html.escape(str(d['max_price']))} ₽, "
            f"экономия {html.escape(str(d['savings']))} ₽ / {html.escape(str(d['savings_pct']))}%)\n"
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
            f"{html.escape(str(a['direction']))} <a href='{html.escape(str(a['url']), quote=True)}'>{html.escape(str(a['name'])[:55])}</a>\n"
            f"   {html.escape(str(a['old_price']))} ₽ → {html.escape(str(a['new_price']))} ₽ ({html.escape(str(a['change_pct']))}%)\n"
        )

    # AI-комментарий
    if len(anomalies) > 0:
        names = ", ".join(a["name"][:30] for a in anomalies[:3])
        ai_comment = await agent._ask_claude(
            f"Резкие изменения цен на товары: {names}. "
            f"Дай краткий комментарий — это распродажа, накрутка или что-то другое? "
            f"Что посоветуешь покупателю?"
        )
        lines.append(f"\n🤖 <b>AI говорит:</b>\n{html.escape(ai_comment)}")

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ── /list ─────────────────────────────────────────────────────────────────────
@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    if not await ensure_allowed(message):
        return
    products, latest_by_product = await telegram_read_service.get_recent_products_with_prices(limit=20)
    if not products:
        return await message.answer(_h_empty_db())

    await message.answer(format_product_list(products, latest_by_product), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not await ensure_allowed(message):
        return
    n_products, n_history, n_subscribers = await telegram_read_service.get_status_counts()
    await message.answer(
        format_status_message(n_products, n_history, n_subscribers, agent._is_available()),
        parse_mode="HTML",
    )


@dp.message(Command("net_diag"))
async def cmd_net_diag(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer(_h_network())

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
    await message.answer(_h_sub_ok())


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    if not await ensure_allowed(message):
        return
    await db.remove_subscriber(message.from_user.id)
    await message.answer(_h_unsub_ok())


async def _broadcast_changes():
    try:
        two_h_ago = datetime.now(UTC) - timedelta(hours=2)
        rows = await telegram_read_service.get_recent_price_changes(two_h_ago, limit=20)

        if not rows:
            return

        lines = ["📊 <b>Изменения цен:</b>"]
        for ph, p in rows:
            icon = "✅" if ph.availability_status == "in_stock" else "❌"
            lines.append(f"{icon} {p.name[:40]}: {ph.price} ₽")

        text = "\n".join(lines)
        subscribers = await telegram_read_service.get_subscriber_ids()
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
    from app.ai_client import close_ai_clients

    try:
        return await run_telegram_polling(
            db=db,
            dp=dp,
            commands=TELEGRAM_COMMANDS,
            set_active_bot=_set_active_bot,
        )
    finally:
        await close_ai_clients()

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
                f"{idx}. {stock} <a href='{html.escape(str(deal['url']), quote=True)}'>{html.escape(str(deal['name'])[:70])}</a>\n"
                f"   💰 <b>{html.escape(str(deal['price']))} ₽</b> (было {html.escape(str(deal['old_price']))} ₽, -{html.escape(str(deal['discount_pct']))}%)"
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

    await message.answer(f"🔎 Сравниваю цены: <b>{html.escape(query)}</b>...", parse_mode="HTML")
    try:
        from app.parsers.wildberries import WildberriesParser

        ozon_results = await search_ozon(query, max_results=1)
        wb_results = await WildberriesParser().search(query, max_results=1)
        if not ozon_results:
            all_results = await search_all_marketplaces(
                query,
                max_per_site=1,
                exclude_marketplaces=("ozon",) if ozon_search_blocked_message() else (),
            )
            ozon_results = all_results.get("ozon", [])

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
            lines.append(f"🔵 <a href='{html.escape(str(r['url']), quote=True)}'>Ozon</a>: <b>{html.escape(str(price))}</b>")
        if wb_results:
            r = wb_results[0]
            price = f"{r.price} ₽" if r.price else "цена не определена"
            lines.append(f"🟣 <a href='{html.escape(str(r.url), quote=True)}'>Wildberries</a>: <b>{html.escape(str(price))}</b>")

        advice = await agent.compare_prices(product_name, ozon_price, wb_price)
        await message.answer(
            "\n".join(lines) + f"\n\n{advice}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Ошибка сравнения цен")
        await message.answer("❌ Ошибка сравнения цен. Попробуйте позже.")


# ── /reviews — анализ отзывов конкретного товара ──────────────────────────────
@dp.message(Command("reviews"))
async def cmd_reviews(message: types.Message, state: FSMContext):
    """Анализирует отзывы последнего добавленного WB-товара."""
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    products = await telegram_read_service.get_recent_wildberries_products(limit=5)

    if not products:
        return await message.answer(
            "📭 Нет товаров с Wildberries.\n"
            "Добавьте через /wb — WB отдаёт отзывы через API."
        )

    lines = ["Выберите товар для анализа отзывов (ответьте номером):\n"]
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {html.escape(str(p.name or 'товар')[:50])}")
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

    product = await telegram_read_service.get_product_by_id(product_ids[choice - 1])
    if not product:
        return await message.answer("❌ Товар не найден.")

    await message.answer(f"🧠 Загружаю и анализирую отзывы: <b>{html.escape(str(product.name or 'товар')[:60])}</b>...", parse_mode="HTML")
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
        await message.answer(html.escape(str(result)), parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        logger.exception("Ошибка анализа отзывов")
        await message.answer("❌ Ошибка анализа отзывов. Попробуйте позже.")


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
        logger.exception("CSV export error")
        await message.answer(f"Export error: {e}")


@dp.message(Command("export_excel"))
async def cmd_export_excel(message: types.Message):
    if not await ensure_allowed(message):
        return
    await message.answer("Preparing Excel file...")
    try:
        await send_price_export(bot, db, message.chat.id, "excel")
    except Exception as e:
        logger.exception("Excel export error")
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
    await message.answer(_h_report())
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

    await _auto_generate_blocked_ozon_cards(message, urls)


async def handle_natural_card_urls(message: types.Message, urls: list[str]):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят. Подождите.")

    await parser_lock.acquire()
    await message.answer("🚀 Нашёл ссылку для карточки, сначала получаю данные товара...")
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
        f"🧩 Данные получил, собираю карточку:\n<b>{html.escape(str(product.name or 'товар')[:80])}</b>",
        parse_mode="HTML",
    )
    await generate_ozon_card_files(message, task, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile)


async def handle_natural_search(message: types.Message, query: str):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    is_valid, validation_error = validate_search_query(query)
    if not is_valid:
        return await message.answer(f"⚠️ {html.escape(str(validation_error))}", parse_mode="HTML")

    await parser_lock.acquire()
    await message.answer(f"🔍 Понял запрос. Ищу на Озоне: <b>{html.escape(query)}</b>...", parse_mode="HTML")
    try:
        results = await search_ozon(query, max_results=5)
        if not results:
            blocked_message = ozon_search_blocked_message()
            await message.answer(
                "🔁 На Ozon сейчас пусто или поиск недоступен. Сразу проверяю другие маркетплейсы..."
            )
            all_results = await search_all_marketplaces(
                query,
                max_per_site=5,
                exclude_marketplaces=("ozon",) if blocked_message else (),
            )
            if _marketplace_result_count(all_results):
                return await message.answer(
                    _format_cross_marketplace_results(
                        all_results,
                        title=f"Нашёл варианты по запросу: {query}",
                        empty_message="",
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
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
                f"{i}. <a href='{html.escape(str(r['url']), quote=True)}'>{html.escape(str(r['name'])[:60])}</a>\n"
                f"   💰 {html.escape(str(price_str))}"
            )

        lines.append("\n💡 Чтобы добавить товар в мониторинг, просто пришлите его ссылку.")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка свободного поиска")
        await message.answer(f"❌ Ошибка поиска: {e}")
    finally:
        parser_lock.release()


async def handle_wildberries_search(message: types.Message, query: str):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    query = _clean_marketplace_search_query(query)
    if not query:
        return await message.answer(
            "Напишите, что искать на Wildberries. Например: <code>витамины магний иммунитет</code>",
            parse_mode="HTML",
        )

    await parser_lock.acquire()
    await message.answer(f"🔍 Понял запрос. Ищу на Wildberries: <b>{html.escape(query)}</b>...", parse_mode="HTML")
    try:
        results = await WildberriesParser().search(query, max_results=5)
        if not results:
            await message.answer("🔁 На Wildberries пусто. Сразу проверяю другие маркетплейсы...")
            all_results = await search_all_marketplaces(
                query,
                max_per_site=5,
                exclude_marketplaces=("ozon",) if ozon_search_blocked_message() else (),
            )
            all_results["wildberries"] = []
            if _marketplace_result_count(all_results):
                return await message.answer(
                    _format_cross_marketplace_results(
                        all_results,
                        title=f"Нашёл варианты на других маркетплейсах: {query}",
                        empty_message="",
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return await message.answer(
                "😔 Ничего не найдено ни на Wildberries, ни на других доступных маркетплейсах. "
                "Попробуйте точнее: например <code>витамины магний иммунитет шипучие</code>.",
                parse_mode="HTML",
            )

        lines = [f"🟣 <b>Найдено {len(results)} товаров на Wildberries:</b>\n"]
        for i, product in enumerate(results, 1):
            price_str = f"{product.price} ₽" if product.price is not None else "цена не определена"
            availability = product.availability or "наличие не определено"
            lines.append(
                f"{i}. <a href='{html.escape(product.url)}'>{html.escape((product.name or 'товар')[:80])}</a>\n"
                f"   💰 {html.escape(str(price_str))} · {html.escape(availability)}"
            )

        lines.append("\n💡 Чтобы добавить товар в мониторинг, пришлите его ссылку.")
        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Ошибка поиска Wildberries")
        await message.answer(f"❌ Ошибка поиска Wildberries: {e}")
    finally:
        parser_lock.release()








async def handle_wildberries_card_search(message: types.Message, query: str):
    if not allowed(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    if parser_lock.locked():
        return await message.answer("⚠️ Парсер занят.")

    query = _clean_marketplace_search_query(query)
    if not query:
        return await message.answer(
            "Не понял, какой товар искать на Wildberries. Напишите, например: "
            "<code>найди на Wildberries витамины с магнием и создай карточку</code>",
            parse_mode="HTML",
        )

    await parser_lock.acquire()
    await message.answer(
        f"🔍 Ищу на Wildberries товар для карточки: <b>{html.escape(query)}</b>...",
        parse_mode="HTML",
    )
    try:
        results = await WildberriesParser().search(query, max_results=5)
    except Exception as e:
        logger.exception("Ошибка поиска Wildberries для карточки")
        parser_lock.release()
        return await message.answer(f"❌ Ошибка поиска Wildberries: {e}")
    else:
        parser_lock.release()

    if not results:
        await message.answer("🔁 На Wildberries не нашёл. Проверяю другие маркетплейсы для карточки...")
        await parser_lock.acquire()
        try:
            all_results = await search_all_marketplaces(
                query,
                max_per_site=5,
                exclude_marketplaces=("ozon",) if ozon_search_blocked_message() else (),
            )
            all_results["wildberries"] = []
        finally:
            parser_lock.release()
        product = _first_marketplace_product(all_results, preferred=("ozon", "yandex_market"))
        if product:
            await message.answer(
                "🧩 Нашёл товар на другом маркетплейсе и собираю карточку:\n"
                f"<b>{html.escape((product.name or 'товар')[:120])}</b>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return await generate_ozon_card_files(
                message, _build_card_task_from_product_data(product),
                parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile,
            )

        await message.answer(
            "⚠️ Доступные маркетплейсы сейчас не отдали товары. "
            "Не останавливаюсь: соберу красивый черновик карточки по самому запросу."
        )
        fallback_task = "\n".join([
            f"товар: {query}",
            "бренд: Нет бренда",
            "категория: витамины и БАДы",
            "задача: создать максимально привлекательную карточку товара с сильным SEO, выгодами и понятным описанием",
            "примечание: Wildberries не отдал данные поиска, карточка создана как черновик по запросу пользователя",
        ])
        return await generate_ozon_card_files(
            message, fallback_task, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile,
        )

    product = next((item for item in results if item.price is not None and item.image_url), results[0])
    await message.answer(
        "🟣 Нашёл товар и собираю карточку:\n"
        f"<b>{html.escape((product.name or 'товар')[:120])}</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await generate_ozon_card_files(
        message, _build_card_task_from_product_data(product),
        parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile,
    )


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
        await generate_ozon_batch_card_files(
            message, payload, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile, db=db,
        )
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
        await generate_ozon_card_files(message, payload, parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile)
        return True
    if intent == "ozon_card_prompt":
        await cmd_ozon_card(message, state)
        return True
    if intent == "card_research":
        await run_card_research(message, payload)
        return True
    if intent == "conversation":
        await message.answer(_conversation_response(payload))
        return True
    if intent == "task_instruction":
        await message.answer(
            "Я не буду отправлять это в поиск Ozon: это служебная инструкция, а не товарный запрос.\n\n"
            "Пришлите конкретную ссылку товара или ТЗ текстом. Если нужен план, напишите саму задачу одним сообщением."
        )
        return True
    if intent == "wildberries_search":
        get_chat_context(message.chat.id).last_marketplace_query = _clean_product_search_query(payload)
        await handle_wildberries_search(message, payload)
        return True
    if intent == "wildberries_card_search":
        get_chat_context(message.chat.id).last_marketplace_query = _clean_product_search_query(payload)
        await handle_wildberries_card_search(message, payload)
        return True
    if intent == "search":
        get_chat_context(message.chat.id).last_marketplace_query = _clean_product_search_query(payload)
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
            await generate_ozon_batch_card_files(
                message, "\n".join(card_sources),
                parser_lock=parser_lock, bot=bot, get_active_profile=get_active_profile, db=db,
            )
            if not other_tasks:
                return
            tasks = other_tasks

        await message.answer(f"Принял задач: <b>{len(tasks)}</b>. Выполню по очереди.", parse_mode="HTML")
        for index, task in enumerate(tasks, 1):
            intent, payload = parse_natural_request(task, context=context)
            if intent == "unknown":
                await message.answer(f"⚠️ Задача {index}: не понял «{task[:80]}».")
                continue
            await message.answer(f"▶️ Задача {index}/{len(tasks)}: <code>{html.escape(task[:120])}</code>", parse_mode="HTML")
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
