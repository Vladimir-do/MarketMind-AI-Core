"""Telegram scraping preflight, task formatting, and handler logic.

Extracted from bot.py to reduce module size. Functions that depend on bot-level
globals (task_planner, parser_lock, get_chat_context, fetch_html) use lazy
imports from app.bot at call time so that tests patching bot_module.* still work.
"""
import csv
import html
import io
from dataclasses import dataclass

from aiogram import types

from app.agent_loop import build_agent_loop, stage_label_ru
from app.config import logger
from app.task_intents import StructuredTask, TaskType
from app.task_planner import SkillStatus
from app.universal_parsing_core.schemas.page_structure import PageStructure


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
    from app.bot import fetch_html
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
    if "ozon.ru" in url.lower():
        from app.generic_scraper import fetch_html_browser as _fetch_html_browser
        return await _fetch_html_browser(url)
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
    from app.bot import fetch_html

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


def format_structured_task_plan(task: StructuredTask) -> str:
    from app.bot import task_planner

    if task.type is TaskType.REPAIR:
        plan = task_planner.build_plan(task)
        agent_loop = build_agent_loop(task)
        lines = ["🔧 <b>Понял repair-задачу.</b>"]
        if task.target_url:
            lines.append(f"Цель: <code>{html.escape(task.target_url)}</code>")
        if task.parameters:
            for key in ("failure_area", "severity", "blast_radius", "evidence_types", "verification_scope", "safety_gates"):
                if key in task.parameters:
                    lines.append(f"{html.escape(key)}: <code>{html.escape(str(task.parameters[key]))}</code>")
            if task.parameters.get("last_error_text"):
                lines.append(f"last_error_text: <code>{html.escape(str(task.parameters['last_error_text'])[:500])}</code>")
            if task.parameters.get("last_validation_warnings"):
                lines.append(f"last_validation_warnings: <code>{html.escape(str(task.parameters['last_validation_warnings'])[:500])}</code>")
        lines.append("")
        lines.append("<b>Цикл ремонта:</b>")
        lines.append(" → ".join(html.escape(stage_label_ru(step.stage)) for step in agent_loop.steps))
        lines.append(f"Стратегия: <code>{html.escape(agent_loop.strategy)}</code>")
        lines.append("")
        for step in plan.steps:
            marker = "✅" if step.status is SkillStatus.AVAILABLE else "🧩" if step.status is SkillStatus.PLANNED else "⚠️"
            lines.append(
                f"{step.index}. {marker} <code>{html.escape(step.skill_id)}</code> "
                f"[q={step.quality_score:.2f}] — {html.escape(step.action)}"
            )
        if plan.self_critic:
            lines.append("")
            lines.append("<b>Самопроверка:</b>")
            lines.extend(f"• {html.escape(_localize_bot_text(check))}" for check in plan.self_critic)
        lines.append("")
        lines.append("Далее нужно воспроизвести failure signal, добавить регрессию, внести фикс и прогнать verification scope.")
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


async def handle_scraping_task(message: types.Message, task: StructuredTask) -> None:
    from app.bot import get_chat_context, parser_lock, task_planner
    from app.generic_scraper import ScrapingError, run_scraping_task

    if task.target_url and "ozon.ru" in task.target_url.lower():
        return await _handle_ozon_scraping(message, task)

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


async def _handle_ozon_scraping(message: types.Message, task: StructuredTask) -> None:
    from app.bot import get_chat_context, parser_lock
    from app.parsers.alt_sources import fetch_ozon_search_api, fetch_from_alt_sources

    await parser_lock.acquire()
    try:
        query = task.parameters.get("query", "")
        if not query:
            from urllib.parse import urlparse
            parsed = urlparse(task.target_url)
            path_parts = parsed.path.strip("/").split("/")
            if "product" in path_parts:
                idx = path_parts.index("product")
                if idx + 1 < len(path_parts):
                    slug = path_parts[idx + 1]
                    query = slug.replace("-", " ")[:50]

        if not query:
            query = "товар"

        await message.answer(f"🔍 Ищу товар через Ozon API: <b>{html.escape(query)}</b>...", parse_mode="HTML")

        results = await fetch_ozon_search_api(query)

        if not results:
            alt_data = await fetch_from_alt_sources(task.target_url, query)
            if alt_data:
                results = [alt_data]

        if not results:
            await message.answer(
                "😔 Не удалось найти товар через Ozon API. "
                "Попробуйте изменить запрос или отправить ссылку на товар."
            )
            return

        product = results[0]
        name = product.get("name", "Без названия")
        price = product.get("price", "неизвестна")
        product_url = product.get("url", task.target_url)

        result_text = (
            f"✅ <b>Товар найден через Ozon API:</b>\n"
            f"📦 {html.escape(name[:100])}\n"
            f"💰 Цена: {price} ₽\n"
            f"🔗 {html.escape(product_url[:80])}\n"
        )

        if len(results) > 1:
            result_text += f"\n📋 Найдено ещё {len(results) - 1} товаров по запросу."

        await message.answer(result_text, parse_mode="HTML", disable_web_page_preview=True)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["name", "price", "url"])
        writer.writeheader()
        for r in results[:10]:
            writer.writerow({
                "name": r.get("name", ""),
                "price": r.get("price", ""),
                "url": r.get("url", ""),
            })

        csv_bytes = output.getvalue().encode("utf-8")
        filename = f"ozon_search_{query[:30].replace(' ', '_')}.csv"
        await message.answer_document(
            types.BufferedInputFile(csv_bytes, filename=filename),
            caption=f"Результаты поиска Ozon: {html.escape(query[:30])}",
        )

        get_chat_context(message.chat.id).clear_failure()

    except Exception as exc:
        logger.exception("Ozon API search failed")
        get_chat_context(message.chat.id).remember_failure(
            task,
            error_text=str(exc),
            error_type=type(exc).__name__,
        )
        await message.answer(f"❌ Ошибка поиска Ozon: {html.escape(str(exc)[:200])}", parse_mode="HTML")
    finally:
        parser_lock.release()


async def handle_repair_task(message: types.Message, task: StructuredTask) -> None:
    await message.answer(format_structured_task_plan(task), parse_mode="HTML", disable_web_page_preview=True)
    await message.answer(build_repair_diagnostic_report(task), parse_mode="HTML", disable_web_page_preview=True)
