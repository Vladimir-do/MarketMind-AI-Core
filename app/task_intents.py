from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from app.parsers.yandex_market import is_yandex_market_url


class TaskType(StrEnum):
    UNKNOWN = "unknown"
    PAGE_CLASSIFICATION_TRAINING = "page_classification_training"
    REPAIR = "repair_task"
    SCRAPING = "scraping_task"
    MARKETPLACE_SEARCH = "marketplace_search"
    CARD_GENERATION = "card_generation"
    UPDATE = "update_task"
    ANALYTICS = "analytics_task"
    BATCH = "batch_task"
    ADD_URLS = "add_urls"
    STATUS = "status_task"
    LIST = "list_task"


@dataclass(slots=True)
class LastFailureMemory:
    task_type: TaskType
    error_text: str
    error_type: str = "unknown"
    target_url: str | None = None
    target_urls: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    output: str | None = None
    requirements: list[str] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)
    metrics: dict[str, object] = field(default_factory=dict)
    created_files: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_task(
        cls,
        task: "StructuredTask",
        *,
        error_text: str,
        error_type: str = "unknown",
        metrics: dict[str, object] | None = None,
        created_files: list[str] | None = None,
        validation_warnings: list[str] | None = None,
    ) -> "LastFailureMemory":
        return cls(
            task_type=task.type,
            error_text=error_text,
            error_type=error_type,
            target_url=task.target_url,
            target_urls=list(task.target_urls),
            fields=list(task.fields),
            output=task.output,
            requirements=list(task.requirements),
            parameters=dict(task.parameters),
            metrics=dict(metrics or {}),
            created_files=list(created_files or []),
            validation_warnings=list(validation_warnings or _split_failure_warnings(error_text)),
        )


@dataclass(slots=True)
class StructuredTask:
    type: TaskType
    raw_text: str
    target_url: str | None = None
    target_urls: list[str] = field(default_factory=list)
    query: str | None = None
    fields: list[str] = field(default_factory=list)
    output: str | None = None
    requirements: list[str] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)
    payload: str | list[str] | None = None
    confidence: float = 0.0
    plan: list[str] = field(default_factory=list)

    def with_context(self, context: "ContextSession | None") -> "StructuredTask":
        if not context or not context.current_task:
            return self
        if self.type is TaskType.REPAIR:
            failure = context.last_failure
            merged = context.current_task
            parameters = dict(self.parameters)
            previous_task_type = failure.task_type if failure else merged.type
            previous_target_url = (failure.target_url if failure else None) or merged.target_url
            previous_target_urls = (failure.target_urls if failure else []) or merged.target_urls
            parameters.setdefault("previous_task_type", previous_task_type.value)
            if previous_target_url and not self.target_url:
                parameters.setdefault("previous_target_url", previous_target_url)
            if failure:
                parameters.setdefault("last_error_text", failure.error_text)
                parameters.setdefault("last_error_type", failure.error_type)
                if failure.parameters.get("task_type"):
                    parameters.setdefault("previous_domain_task_type", failure.parameters["task_type"])
                if failure.parameters.get("entity_type"):
                    parameters.setdefault("previous_entity_type", failure.parameters["entity_type"])
                if failure.validation_warnings:
                    parameters.setdefault("last_validation_warnings", list(failure.validation_warnings))
                if failure.metrics:
                    parameters.setdefault("last_result_metrics", dict(failure.metrics))
                if failure.created_files:
                    parameters.setdefault("last_created_files", list(failure.created_files))
            if parameters.get("failure_area") == "unknown" and previous_task_type is TaskType.SCRAPING:
                inherited_has_url = bool(previous_target_url or self.target_url)
                evidence_types = _detect_repair_evidence_types(
                    f"{self.raw_text}\n{failure.error_text if failure else ''}".lower()
                )
                parameters["failure_area"] = "parser"
                parameters["evidence_types"] = evidence_types
                parameters["severity"] = _detect_repair_severity(
                    f"{self.raw_text}\n{failure.error_text if failure else ''}".lower(),
                    evidence_types,
                )
                parameters["blast_radius"] = "localized"
                parameters["verification_scope"] = _repair_verification_scope(
                    failure_area="parser",
                    blast_radius="localized",
                    has_url=inherited_has_url,
                )
                parameters["safety_gates"] = _repair_safety_gates(has_url=inherited_has_url)
                parameters["requires_full_tests"] = False
                parameters["requires_live_smoke"] = inherited_has_url
            return StructuredTask(
                type=self.type,
                raw_text=self.raw_text,
                target_url=self.target_url or previous_target_url,
                target_urls=list(self.target_urls or previous_target_urls),
                query=self.query,
                fields=list(self.fields),
                output=self.output,
                requirements=list(self.requirements),
                parameters=parameters,
                payload=self.payload,
                confidence=self.confidence,
                plan=list(self.plan),
            )
        additions = []
        for item in _extract_field_like_lines(self.raw_text):
            if not _is_context_field_candidate(item):
                continue
            normalized = item.lower().strip().replace(" ", "_")
            additions.append(_canonical_field_name(normalized) or normalized)
        if self.type is not TaskType.UNKNOWN and not (
            self.type in {TaskType.MARKETPLACE_SEARCH, TaskType.CARD_GENERATION}
            and context.current_task.type is TaskType.SCRAPING
            and additions
        ):
            return self
        if not additions:
            return self
        merged = context.current_task
        fields = list(dict.fromkeys([*merged.fields, *additions]))
        return StructuredTask(
            type=merged.type,
            raw_text=f"{merged.raw_text}\n{self.raw_text}".strip(),
            target_url=merged.target_url,
            target_urls=list(merged.target_urls),
            query=merged.query,
            fields=fields,
            output=merged.output,
            requirements=list(merged.requirements),
            parameters=dict(merged.parameters),
            payload=merged.payload,
            confidence=min(1.0, merged.confidence + 0.05),
            plan=_build_plan(merged.type, merged.target_url, fields, merged.output, merged.requirements, merged.parameters),
        )


@dataclass(slots=True)
class ContextSession:
    current_task: StructuredTask | None = None
    last_failure: LastFailureMemory | None = None
    active_intent: TaskType | None = None
    status: str | None = None

    def remember(self, task: StructuredTask) -> None:
        if task.type in {TaskType.REPAIR, TaskType.SCRAPING, TaskType.BATCH, TaskType.CARD_GENERATION}:
            self.current_task = task
            self.clear_active()
        if task.type is TaskType.PAGE_CLASSIFICATION_TRAINING:
            self.current_task = task
            self.active_intent = task.type
            self.status = "нужен URL страницы для анализа"

    def remember_failure(
        self,
        task: StructuredTask,
        *,
        error_text: str,
        error_type: str = "unknown",
        metrics: dict[str, object] | None = None,
        created_files: list[str] | None = None,
        validation_warnings: list[str] | None = None,
    ) -> None:
        self.current_task = task
        self.last_failure = LastFailureMemory.from_task(
            task,
            error_text=error_text,
            error_type=error_type,
            metrics=metrics,
            created_files=created_files,
            validation_warnings=validation_warnings,
        )
        self.clear_active()

    def clear_failure(self) -> None:
        self.last_failure = None

    def waiting_for_page_classification_url(self) -> bool:
        return (
            self.active_intent is TaskType.PAGE_CLASSIFICATION_TRAINING
            and self.status == "нужен URL страницы для анализа"
        )

    def clear_active(self) -> None:
        self.active_intent = None
        self.status = None

    def should_continue_page_classification(self, urls: list[str], raw_text: str | None = None) -> bool:
        if not self.waiting_for_page_classification_url() or not urls:
            return False
        if raw_text and _has_explicit_scraping_command(raw_text.lower()):
            return False
        return True


@dataclass(frozen=True, slots=True)
class NormalizedTaskSpec:
    raw_text: str
    fields: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)
    output: str | None = None
    field_normalization_required: bool = False


def extract_urls(text: str) -> list[str]:
    return [url.rstrip(".,);]}>") for url in re.findall(r"https?://\S+", text or "", flags=re.I)]


def is_supported_marketplace_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return "ozon.ru" in host or "wildberries.ru" in host or "wb.ru" in host or is_yandex_market_url(url)


def extract_supported_urls(text: str) -> list[str]:
    return [url for url in extract_urls(text) if is_supported_marketplace_url(url)]


def detect_task_intent(text: str, context: ContextSession | None = None) -> StructuredTask:
    raw = (text or "").strip()
    if not raw:
        return StructuredTask(TaskType.UNKNOWN, raw, confidence=0.0)

    low = raw.lower()
    urls = extract_urls(raw)
    marketplace_urls = [url for url in urls if is_supported_marketplace_url(url)]

    task = _detect_without_context(raw, low, urls, marketplace_urls)
    task = task.with_context(context)
    if context:
        context.remember(task)
    return task


def is_single_context_task(text: str) -> bool:
    task = detect_task_intent(text)
    return task.type is TaskType.SCRAPING


def _detect_without_context(
    raw: str,
    low: str,
    urls: list[str],
    marketplace_urls: list[str],
) -> StructuredTask:
    if _looks_like_repair_task(low):
        return _build_repair_task(raw, urls)

    if _looks_like_page_classification_training(raw, low):
        return StructuredTask(
            TaskType.PAGE_CLASSIFICATION_TRAINING,
            raw,
            target_url=urls[0] if urls else None,
            target_urls=urls,
            confidence=0.95,
            plan=[
                "classify_page_before_parsing",
                "detect_task_type",
                "detect_page_structure",
                "estimate_confidence",
            ],
        )

    if _looks_like_scraping_task(raw, low, urls):
        return _build_scraping_task(raw, urls)

    if _is_update(low):
        return StructuredTask(TaskType.UPDATE, raw, confidence=0.9, plan=["Обновить отслеживаемые товары"])

    if re.search(r"\b(список|покажи товары|что отслеж|отслеживаем)\b", low):
        return StructuredTask(TaskType.LIST, raw, confidence=0.85, plan=["Показать отслеживаемые товары"])

    if re.search(r"\b(статус|сколько товаров|состояние базы|база)\b", low):
        return StructuredTask(TaskType.STATUS, raw, confidence=0.85, plan=["Показать статус базы"])

    if _mentions_card(low):
        if len(marketplace_urls) > 1 or _mentions_batch(low):
            return StructuredTask(
                TaskType.BATCH,
                raw,
                target_urls=marketplace_urls,
                payload=raw,
                confidence=0.85,
                plan=["Разобрать список источников", "Собрать карточки", "Экспортировать XLSX/JSON"],
            )
        payload = _extract_card_payload(raw)
        return StructuredTask(
            TaskType.CARD_GENERATION,
            raw,
            target_urls=marketplace_urls,
            payload=marketplace_urls if marketplace_urls else payload,
            confidence=0.85 if payload or marketplace_urls else 0.65,
            plan=["Собрать черновик карточки", "Проверить обязательные поля", "Экспортировать XLSX/JSON"],
        )

    if _mentions_analytics(low):
        query = _extract_after_patterns(
            raw,
            [
                r"^(?:проанализируй|анализ|посмотри|изучи|разбери)\s+(?:мне\s+)?(?:конкурентов|выдачу|рынок)(?:\s+(?:для|по|на|товара?))?\s+(.+)$",
                r"^(?:конкуренты|анализ конкурентов|анализ выдачи|рынок)\s+(?:для|по|на|товара?)\s+(.+)$",
            ],
        )
        return StructuredTask(
            TaskType.ANALYTICS,
            raw,
            query=query,
            payload=query,
            confidence=0.8 if query else 0.65,
            plan=["Собрать выдачу конкурентов", "Посчитать сводку", "Сформировать рекомендации"],
        )

    if marketplace_urls:
        return StructuredTask(
            TaskType.ADD_URLS,
            raw,
            target_urls=marketplace_urls,
            payload=marketplace_urls,
            confidence=0.9,
            plan=["Определить marketplace", "Получить данные товара", "Сохранить в мониторинг"],
        )

    query = _extract_search_query(raw)
    if query:
        return StructuredTask(
            TaskType.MARKETPLACE_SEARCH,
            raw,
            query=query,
            payload=query,
            confidence=0.75,
            plan=["Искать товар на marketplace", "Показать результаты", "Дать возможность добавить товар"],
        )

    return StructuredTask(TaskType.UNKNOWN, raw, confidence=0.0)


def _looks_like_repair_task(low: str) -> bool:
    explicit_repair_markers = (
        "fix",
        "repair",
        "bug",
        "\u0438\u0441\u043f\u0440\u0430\u0432\u044c",
        "\u043f\u043e\u0447\u0438\u043d\u0438",
        "\u0447\u0442\u043e\u0431\u044b \u0438\u0441\u043f\u0440\u0430\u0432\u043b\u044f\u043b",
    )
    failure_report_markers = (
        "failed",
        "failure",
        "traceback",
        "pytest failed",
        "no product records were extracted",
        "\u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442",
        "\u043d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u043e\u0441\u044c",
        "\u0430\u0433\u0435\u043d\u0442 \u043e\u0448\u0438\u0431",
        "\u0430\u0433\u0435\u043d\u0442 \u043d\u0435",
        "\u043f\u0430\u0440\u0441\u0435\u0440 \u0443\u043f\u0430\u043b",
        "\u043f\u0430\u0434\u0430\u0435\u0442",
        "\u0441\u043b\u043e\u043c\u0430\u043b",
        "\u043d\u0435 \u0441\u043f\u0430\u0440\u0441",
        "\u043d\u0435 \u0441\u043e\u0431\u0440\u0430\u043b",
    )
    return any(marker in low for marker in explicit_repair_markers) or any(
        marker in low for marker in failure_report_markers
    )


def _split_failure_warnings(error_text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r";|\n", error_text or "")
        if item.strip()
    ]


def _build_repair_task(raw: str, urls: list[str]) -> StructuredTask:
    low = raw.lower()
    failure_area = _detect_failure_area(low)
    blast_radius = _detect_repair_blast_radius(low, failure_area)
    evidence_types = _detect_repair_evidence_types(low)
    parameters: dict[str, object] = {
        "repair_mode": "regression_first",
        "failure_area": failure_area,
        "severity": _detect_repair_severity(low, evidence_types),
        "evidence_types": evidence_types,
        "blast_radius": blast_radius,
        "verification_scope": _repair_verification_scope(
            failure_area=failure_area,
            blast_radius=blast_radius,
            has_url=bool(urls),
        ),
        "safety_gates": _repair_safety_gates(has_url=bool(urls)),
        "requires_regression_test": True,
        "requires_focused_tests": True,
        "requires_full_tests": blast_radius == "shared",
        "requires_live_smoke": bool(urls) and failure_area in {"parser", "network_or_antibot", "page_structure"},
        "requires_skillpack_update": True,
    }
    return StructuredTask(
        TaskType.REPAIR,
        raw,
        target_url=urls[0] if urls else None,
        target_urls=urls,
        parameters=parameters,
        confidence=0.9,
        plan=[
            "classify_failure",
            "assess_severity_and_blast_radius",
            "check_safety_gates",
            "reproduce_or_capture_signal",
            "add_regression_test",
            "implement_smallest_fix",
            "run_focused_tests",
            "run_full_tests_if_shared",
            "update_skillpack",
        ],
    )


def _detect_failure_area(low: str) -> str:
    if any(marker in low for marker in ("page_structure", "empty", "unknown_js", "\u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440", "\u043f\u0443\u0441\u0442\u0430\u044f \u0441\u0442\u0440\u0430\u043d")):
        return "page_structure"
    if any(marker in low for marker in ("intent", "context", "task_type", "\u043d\u0430\u043c\u0435\u0440\u0435\u043d", "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442")):
        return "intent"
    if any(marker in low for marker in ("parse", "scrape", "extract", "selector", "html", "\u043f\u0430\u0440\u0441", "\u0438\u0437\u0432\u043b\u0435\u043a", "\u0441\u0435\u043b\u0435\u043a\u0442\u043e\u0440")):
        return "parser"
    if any(marker in low for marker in ("csv", "xlsx", "json", "export", "\u044d\u043a\u0441\u043f\u043e\u0440\u0442", "\u0441\u043e\u0445\u0440\u0430\u043d")):
        return "export"
    if any(marker in low for marker in ("pytest", "test", "\u0442\u0435\u0441\u0442")):
        return "test"
    if any(marker in low for marker in ("403", "429", "timeout", "blocked", "captcha", "\u0431\u043b\u043e\u043a", "\u0442\u0430\u0439\u043c\u0430\u0443\u0442")):
        return "network_or_antibot"
    return "unknown"


def _detect_repair_evidence_types(low: str) -> list[str]:
    evidence: list[str] = []
    markers = {
        "traceback": ("traceback", "exception", "stack trace"),
        "failing_test": ("pytest failed", "assertionerror", "test failed", "\u0442\u0435\u0441\u0442 \u043f\u0430\u0434"),
        "empty_extraction": ("no product records were extracted", "0 records", "empty result", "\u043d\u0435 \u0441\u043f\u0430\u0440\u0441", "\u043d\u0435 \u0441\u043e\u0431\u0440\u0430\u043b"),
        "wrong_intent": ("wrong intent", "intent", "task_type", "\u043d\u0435\u0432\u0435\u0440\u043d\u043e \u043f\u043e\u043d\u044f\u043b"),
        "http_status": ("http_status", "403", "429", "500", "502", "503"),
        "bad_output_file": ("csv", "xlsx", "json", "export", "\u0444\u0430\u0439\u043b", "\u044d\u043a\u0441\u043f\u043e\u0440\u0442"),
        "live_smoke": ("live smoke", "smoke", "\u0436\u0438\u0432\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440"),
    }
    for name, values in markers.items():
        if any(value in low for value in values):
            evidence.append(name)
    if not evidence:
        evidence.append("user_report")
    return evidence


def _detect_repair_severity(low: str, evidence_types: list[str]) -> str:
    if re.search(r"\b(security|secret|token)\b", low) or any(marker in low for marker in ("\u0441\u0435\u043a\u0440\u0435\u0442", "\u0442\u043e\u043a\u0435\u043d")):
        return "critical"
    if re.search(r"\b(production|prod)\b", low) or any(marker in low for marker in ("\u043f\u0440\u043e\u0434", "\u0431\u043e\u0435\u0432")):
        return "critical"
    if "traceback" in evidence_types or "failing_test" in evidence_types or "empty_extraction" in evidence_types:
        return "high"
    if any(marker in low for marker in ("docs", "documentation", "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442")):
        return "low"
    return "medium"


def _detect_repair_blast_radius(low: str, failure_area: str) -> str:
    shared_markers = (
        "context",
        "intent",
        "task_type",
        "planner",
        "agent_loop",
        "router",
        "database",
        "worker",
        "telegram",
        "bot",
        "skillpack",
        "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442",
        "\u043d\u0430\u043c\u0435\u0440\u0435\u043d",
        "\u043f\u043b\u0430\u043d",
    )
    if failure_area in {"intent", "test", "unknown"} or any(marker in low for marker in shared_markers):
        return "shared"
    return "localized"


def _repair_verification_scope(*, failure_area: str, blast_radius: str, has_url: bool) -> list[str]:
    scope = ["focused_tests"]
    if blast_radius == "shared":
        scope.append("full_test_suite")
    if has_url and failure_area in {"parser", "network_or_antibot", "page_structure"}:
        scope.append("safe_live_smoke")
    scope.append("skillpack_validator")
    return scope


def _repair_safety_gates(*, has_url: bool) -> list[str]:
    gates = [
        "no_destructive_commands",
        "do_not_revert_unrelated_changes",
        "no_secret_logging",
        "preserve_existing_contracts",
    ]
    if has_url:
        gates.append("network_requires_safe_live_smoke_or_user_approval")
    return gates


def _looks_like_scraping_task(raw: str, low: str, urls: list[str]) -> bool:
    if not urls:
        return False
    scraping_words = (
        "scrape",
        "scraping",
        "scraper",
        "parse",
        "parser",
        "collect",
        "extract",
        "спарси",
        "парси",
        "парсер",
        "парсинг",
        "собери данные",
        "извлеки",
        "проанализируй сайт",
        "спарси",
        "парси",
        "парсер",
        "парсинг",
        "собери данные",
        "извлеки",
        "проанализируй сайт",
    )
    structure_words = (
        "field",
        "fields",
        "поле",
        "поля",
        "need collect",
        "result",
        "requirements",
        "title",
        "price",
        "rating",
        "availability",
        "product_url",
        "csv",
        "xlsx",
        "json",
        "html",
        "поля",
        "требован",
        "результат",
        "сохран",
        "поля",
        "требован",
        "результат",
        "сохран",
    )
    return _has_explicit_scraping_command(low) or any(word in low for word in scraping_words) or (
        "\n" in raw and any(word in low for word in structure_words)
    )


def _has_explicit_scraping_command(low: str) -> bool:
    return bool(
        re.search(r"\b(scrape|parse|collect|extract|export|save)\b", low)
        or any(
            marker in low
            for marker in (
                "СЃРїР°СЂСЃРё",
                "\u0441\u043f\u0430\u0440\u0441\u0438",
                "СЃРѕР±РµСЂРё",
                "\u0441\u043e\u0431\u0435\u0440\u0438",
                "РЅР°Р№РґРё С†РµРЅ",
                "\u043d\u0430\u0439\u0434\u0438 \u0446\u0435\u043d",
                "РІС‹РіСЂСѓР·Рё",
                "\u0432\u044b\u0433\u0440\u0443\u0437\u0438",
                "СЃРѕС…СЂР°РЅРё",
                "\u0441\u043e\u0445\u0440\u0430\u043d\u0438",
                "СЃРґРµР»Р°Р№ csv",
                "\u0441\u0434\u0435\u043b\u0430\u0439 csv",
            )
        )
    )


def _looks_like_page_classification_training(raw: str, low: str | None = None) -> bool:
    low = low if low is not None else (raw or "").lower()
    strong_markers = (
        "не парси сразу",
        "сначала определи",
        "task_type",
        "page_structure",
        "confidence",
    )
    if any(marker in low for marker in strong_markers):
        return True
    return bool(
        re.search(r"\b(открой|open)\b", low)
        and re.search(r"\b(классифицируй|classify|определи)\b", low)
        and re.search(r"\b(page|страниц|структур|тип)\b", low)
    )


def _build_scraping_task(raw: str, urls: list[str]) -> StructuredTask:
    fields = _extract_fields(raw)
    requirements = _extract_requirements(raw)
    parameters = _extract_parameters(raw)
    use_focus_terms = _mentions_restaurant_menu(raw)
    focus_terms = _extract_scraping_focus_terms(raw, urls) if use_focus_terms else []
    if use_focus_terms and focus_terms:
        parameters["focus_terms"] = focus_terms
    if _mentions_restaurant_menu(raw):
        parameters["task_type"] = "restaurant_menu"
        parameters["entity_type"] = "dish"
        parameters["page_structure"] = "catalog_or_unknown_js"
        parameters["next_strategy"] = "browser"
    else:
        parameters.update(_classify_scraping_domain_task(raw, urls, fields))
    if not fields and _mentions_price_assortment(raw):
        fields = ["title", "price", "description", "product_url"]
    output = _extract_output(raw)
    target_url = urls[0] if urls else None
    return StructuredTask(
        TaskType.SCRAPING,
        raw,
        target_url=target_url,
        target_urls=urls,
        fields=fields,
        output=output,
        requirements=requirements,
        parameters=parameters,
        confidence=0.9 if target_url and fields else 0.75,
        plan=_build_plan(TaskType.SCRAPING, target_url, fields, output, requirements, parameters),
    )


def _classify_scraping_domain_task(raw: str, urls: list[str], fields: list[str]) -> dict[str, object]:
    low = raw.lower()
    url = urls[0] if urls else ""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    parameters: dict[str, object] = {}

    if "books.toscrape.com" in host:
        parameters["task_type"] = "product_catalog"
        parameters["entity_type"] = "product"
        parameters["page_structure"] = "catalog_or_single"
        return parameters

    if "quotes.toscrape.com" in host:
        parameters["task_type"] = "text_collection"
        parameters["entity_type"] = "quote"
        parameters["page_structure"] = "catalog_or_article"
        return parameters

    if "jsonplaceholder.typicode.com" in host or "/api/" in path or any(marker in low for marker in (" api ", "json api", "endpoint")):
        parameters["task_type"] = "api_source"
        parameters["entity_type"] = "record"
        parameters["next_strategy"] = "api"
        return parameters

    if host.endswith("fl.ru") or ".fl.ru" in host:
        if "/projects/" in path or "project" in path:
            parameters["task_type"] = "freelance_project"
            parameters["entity_type"] = "project"
            parameters["page_structure"] = "article_or_project"
            return parameters

    if any(marker in path for marker in ("/blog", "/news", "/article", "/articles", "/posts")) or any(
        marker in low for marker in ("\u0441\u0442\u0430\u0442\u044c", "article", "blog post", "news")
    ):
        parameters["task_type"] = "article"
        parameters["entity_type"] = "article"
        parameters["page_structure"] = "article"
        return parameters

    product_fields = {"title", "price", "availability", "rating", "product_url", "image_url"}
    if product_fields.intersection(fields):
        parameters["task_type"] = "product_catalog"
        parameters["entity_type"] = "product"
        parameters["page_structure"] = "catalog_or_single"
        return parameters

    parameters["task_type"] = "universal_page"
    parameters["entity_type"] = "entity"
    parameters["page_structure"] = "unknown"
    return parameters


def _extract_fields(raw: str) -> list[str]:
    known = {
        "title",
        "name",
        "price",
        "availability",
        "rating",
        "product_url",
        "url",
        "image",
        "image_url",
        "description",
        "upc",
        "product_type",
        "tax",
        "number_of_reviews",
    }
    fields = _extract_labeled_fields(raw)
    for item in _extract_field_like_lines(raw):
        normalized = item.lower().strip().replace(" ", "_")
        canonical = _canonical_field_name(normalized)
        if _is_requirement_candidate(normalized):
            continue
        if _is_scope_command_candidate(normalized):
            continue
        if _is_report_instruction_candidate(normalized):
            continue
        if canonical:
            fields.append(canonical)
        elif normalized in known or _is_ascii_field_name(normalized):
            fields.append(normalized)
    return list(dict.fromkeys(fields))


def _extract_labeled_fields(raw: str) -> list[str]:
    fields: list[str] = []
    label_fields = f"{chr(0x43f)}{chr(0x43e)}{chr(0x43b)}{chr(0x44f)}"
    label_field = f"{chr(0x43f)}{chr(0x43e)}{chr(0x43b)}{chr(0x435)}"
    pattern = rf"^\s*(?:fields?|{label_fields}|{label_field})\s*[:=]\s*(.+)$"
    for line in raw.splitlines():
        match = re.match(pattern, line, flags=re.I)
        if not match:
            continue
        for item in re.split(r"[,;]", match.group(1)):
            normalized = item.lower().strip().strip("`'\" :;,.").replace(" ", "_")
            if not normalized:
                continue
            if _is_requirement_candidate(normalized):
                continue
            if _is_report_instruction_candidate(normalized):
                continue
            canonical = _canonical_field_name(normalized)
            if canonical:
                fields.append(canonical)
            elif normalized in {
                "title",
                "name",
                "price",
                "availability",
                "rating",
                "product_url",
                "url",
                "image",
                "image_url",
                "description",
                "upc",
                "product_type",
                "tax",
                "number_of_reviews",
            } or _is_ascii_field_name(normalized):
                fields.append(normalized)
    return fields


def _canonical_field_name(normalized: str) -> str | None:
    aliases = {
        "название": "title",
        "название_книги": "title",
        "название_товара": "title",
        "имя": "title",
        "наименование": "title",
        "цена": "price",
        "цену": "price",
        "стоимость": "price",
        "наличие": "availability",
        "доступность": "availability",
        "рейтинг": "rating",
        "оценка": "rating",
        "ссылка": "product_url",
        "ссылку": "product_url",
        "ссылка_на_карточку": "product_url",
        "ссылку_на_карточку": "product_url",
        "url_карточки": "product_url",
        "картинка": "image_url",
        "изображение": "image_url",
        "фото": "image_url",
        "описание": "description",
    }
    aliases.update({
        "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435": "title",
        "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435_\u043a\u043d\u0438\u0433\u0438": "title",
        "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435_\u0442\u043e\u0432\u0430\u0440\u0430": "title",
        "\u0438\u043c\u044f": "title",
        "\u043d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435": "title",
        "\u0446\u0435\u043d\u0430": "price",
        "\u0446\u0435\u043d\u0443": "price",
        "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c": "price",
        "\u043d\u0430\u043b\u0438\u0447\u0438\u0435": "availability",
        "\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0441\u0442\u044c": "availability",
        "\u0440\u0435\u0439\u0442\u0438\u043d\u0433": "rating",
        "\u043e\u0446\u0435\u043d\u043a\u0430": "rating",
        "\u0441\u0441\u044b\u043b\u043a\u0430": "product_url",
        "\u0441\u0441\u044b\u043b\u043a\u0443": "product_url",
        "\u0441\u0441\u044b\u043b\u043a\u0430_\u043d\u0430_\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443": "product_url",
        "\u0441\u0441\u044b\u043b\u043a\u0443_\u043d\u0430_\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443": "product_url",
        "url_\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438": "product_url",
        "\u043a\u0430\u0440\u0442\u0438\u043d\u043a\u0430": "image_url",
        "\u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435": "image_url",
        "\u0444\u043e\u0442\u043e": "image_url",
        "\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435": "description",
    })
    return aliases.get(normalized)


def _extract_field_like_lines(raw: str) -> list[str]:
    values = []
    for line in raw.splitlines():
        stripped = line.strip()
        match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", stripped)
        candidate = match.group(1).strip() if match else stripped
        candidate = candidate.strip("`'\" :;,.")
        if not candidate:
            continue
        lowered = candidate.lower()
        if "scraping" in lowered:
            continue
        normalized = lowered.strip().replace(" ", "_")
        if _is_scope_command_candidate(normalized):
            continue
        if any(
            marker in lowered
            for marker in (
                "http://",
                "https://",
                "need collect",
                "requirements",
                "result",
                "поля",
                "требован",
                "результат",
                "обязательно",
                "обязательно",
                "требован",
                "результат",
            )
        ):
            continue
        if len(candidate.split()) <= 4:
            values.append(candidate)
    return values


def _is_requirement_candidate(normalized: str) -> bool:
    if _is_requirement_action(normalized):
        return True
    if _is_save_output_command(normalized):
        return True
    return normalized in {
        "field",
        "fields",
        "поля",
        "поле",
        "output",
        "result",
        "вывод",
        "результат",
        "вывод",
        "результат",
        "csv",
        "xlsx",
        "json",
        "html",
        "logging",
        "логирование",
        "добавить_логирование",
        "логирование",
        "retry",
        "ретрай",
        "повтор",
        "ретрай",
        "повтор",
        "error_handling",
        "обработка_ошибок",
        "обработку_ошибок",
        "добавить_обработку_ошибок",
        "обработка_ошибок",
        "delay",
        "delay_between_requests",
        "задержка",
        "задержка_между_запросами",
        "задержка",
        "задержка_между_запросами",
        "pagination",
        "пагинация",
        "задача",
        "пагинация",
        "логирование",
        "обработку_ошибок",
        "обработка_ошибок",
        "задержку_между_запросами",
        "задержка_между_запросами",
        "нормальную_структуру_функций",
    }


def _is_report_instruction_candidate(normalized: str) -> bool:
    return bool(
        normalized in {
            "после_выполнения_напиши",
            "сколько_книг_собрано",
            "какие_файлы_созданы",
            "какие_проблемы_были_найдены",
            "как_можно_улучшить_парсер",
        }
        or normalized.startswith("после_выполнения")
        or normalized.startswith("сколько_")
        or normalized.startswith("какие_")
        or normalized.startswith("как_")
    )


def _is_ascii_field_name(normalized: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_]{1,40}", normalized))


def _is_save_output_command(normalized: str) -> bool:
    save_stem = f"{chr(0x441)}{chr(0x43e)}{chr(0x445)}"
    return "csv" in normalized and (
        "save" in normalized
        or "export" in normalized
        or save_stem in normalized
    )


def _is_requirement_action(normalized: str) -> bool:
    return bool(
        re.search(r"^(добавить|добавь|нужно_добавить|сделай|предусмотри)_", normalized)
        and re.search(r"(логирован|ошиб|ретра|retry|delay|задерж)", normalized)
    )


def _is_scope_command_candidate(normalized: str) -> bool:
    normalized = normalized.strip().replace("-", "_")
    return bool(
        normalized in {
            "собери_все",
            "собери_все_книги",
            "спарси_все",
            "получи_все",
            "получи_все_товары",
            "все_товары",
            "собери_все",
            "собери_все_книги",
            "собери_с_первой_страницы",
            "спарси_все",
            "получи_все",
            "получи_все_товары",
            "все_товары",
            "первая_страница",
            "first_page",
            "all_pages",
            "all_products",
        }
        or re.search(r"\b(собери|спарси|получи|извлеки|collect|scrape|parse|extract)[_\s]+(все|all)\b", normalized)
        or re.search(r"\b(собери|спарси|получи|извлеки)[_\s]+с[_\s]+первой[_\s]+страницы\b", normalized)
        or re.search(r"\ball[_\s]+(pages|products|items)\b", normalized)
    )


def _is_context_field_candidate(value: str) -> bool:
    normalized = value.lower().strip().replace(" ", "_")
    if normalized in {"ok", "okay", "ок", "да", "нет", "спасибо", "понял", "готово"}:
        return False
    if _is_requirement_candidate(normalized):
        return False
    if _is_scope_command_candidate(normalized):
        return False
    return bool(re.fullmatch(r"[a-zа-яё_][\wа-яё_ -]{1,40}", value, flags=re.I))


def _extract_requirements(raw: str) -> list[str]:
    low_map = {
        "logging": ("logging", "логирован"),
        "retry": ("retry", "ретра", "повтор"),
        "delay": ("delay", "задерж"),
        "error handling": ("error handling", "errors", "ошиб"),
        "pagination": ("pagination", "пагинац"),
    }
    low_map.update({
        "logging": (*low_map["logging"], "логирован"),
        "retry": (*low_map["retry"], "ретра", "повтор"),
        "delay": (*low_map["delay"], "задерж"),
        "error handling": (*low_map["error handling"], "ошиб"),
        "pagination": (*low_map["pagination"], "пагинац"),
    })
    low = raw.lower()
    return [name for name, markers in low_map.items() if any(marker in low for marker in markers)]


def _extract_parameters(raw: str) -> dict[str, object]:
    low = raw.lower()
    normalized = low.replace("-", "_")
    params: dict[str, object] = {}
    if "scope=first_page" in normalized or "scope:first_page" in normalized or "first_page" in normalized:
        params["scope"] = "first_page"
    elif (
        re.search(r"\b(собери|спарси|получи|извлеки)\s+все\b", low)
        or re.search(r"\b(собери|спарси|получи|извлеки)\s+данные\s+по\s+всем\b", low)
        or re.search(r"\b(собери|спарси|получи|извлеки)\s+все\b", low)
        or re.search(r"\b(collect|scrape|parse|extract)\s+all\b", low)
        or any(token in normalized for token in ("собери_все", "собери_все_книги", "все_товары", "все_книги", "всем_книгам", "all_pages", "all_products", "all_books"))
    ):
        params["scope"] = "all_pages"
        params["pagination"] = True
    elif re.search(r"\b(собери|спарси|получи|извлеки)\s+с\s+первой\s+страницы\b", low) or "собери_с_первой_страницы" in normalized:
        params["scope"] = "first_page"
    elif "pagination" in low or "пагинац" in low:
        params["pagination"] = True
    return params


def _mentions_price_assortment(raw: str) -> bool:
    low = raw.lower()
    return bool(
        re.search(r"\b(price|prices|цены|цену|прайс|стоимость|ассортимент|меню)\b", low)
    )


def _mentions_restaurant_menu(raw: str) -> bool:
    low = raw.lower()
    return any(
        marker in low
        for marker in (
            "chibbis",
            "С€Р°С€Р»С‹Рє",
            "\u0448\u0430\u0448\u043b\u044b\u043a",
            "РјСЏСЃРѕ",
            "\u043c\u044f\u0441\u043e",
            "РјСЏСЃРЅ",
            "\u043c\u044f\u0441\u043d",
            "РіСЂРёР»СЊ",
            "\u0433\u0440\u0438\u043b\u044c",
            "Р»СЋР»СЏ",
            "\u043b\u044e\u043b\u044f",
            "РєРµР±Р°Р±",
            "\u043a\u0435\u0431\u0430\u0431",
            "РјР°РЅРіР°Р»",
            "\u043c\u0430\u043d\u0433\u0430\u043b",
            "СЂРµСЃС‚РѕСЂР°РЅ",
            "\u0440\u0435\u0441\u0442\u043e\u0440\u0430\u043d",
            "РјРµРЅСЋ",
            "\u043c\u0435\u043d\u044e",
            "РґРѕСЃС‚Р°РІРєР° РµРґС‹",
            "\u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0435\u0434\u044b",
        )
    )


def _extract_scraping_focus_terms(raw: str, urls: list[str]) -> list[str]:
    text = raw
    for url in urls:
        text = text.replace(url, " ")
    low = text.lower()
    stopwords = {
        "http",
        "https",
        "www",
        "site",
        "scrape",
        "parse",
        "parser",
        "спарси",
        "парси",
        "посмотри",
        "собери",
        "извлеки",
        "цены",
        "цену",
        "цена",
        "стоимость",
        "общий",
        "общую",
        "ассортимент",
        "блюд",
        "блюда",
        "меню",
        "и",
        "а",
        "на",
        "по",
        "за",
        "для",
        "с",
        "в",
    }
    candidates = []
    for token in re.findall(r"[a-zа-яё][a-zа-яё-]{2,}", low, flags=re.I):
        token = token.strip("-")
        if token and token not in stopwords:
            candidates.append(token)
    return list(dict.fromkeys(candidates[:12]))


def _extract_output(raw: str) -> str | None:
    low = raw.lower()
    explicit_output = (
        "result",
        "output",
        "export",
        "save",
        "file",
        "\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442",
        "\u0432\u044b\u0432\u043e\u0434",
        "\u044d\u043a\u0441\u043f\u043e\u0440\u0442",
        "\u0441\u043e\u0445\u0440\u0430\u043d",
        "\u0444\u0430\u0439\u043b",
    )
    for line in raw.splitlines():
        line_low = line.lower()
        if not any(marker in line_low for marker in explicit_output):
            continue
        for output in ("csv", "xlsx", "json", "html"):
            if re.search(rf"\b{output}\b", line_low):
                return output
    for output in ("csv", "xlsx", "json"):
        if re.search(rf"\b{output}\b", low):
            return output
    return None


def _build_plan(
    task_type: TaskType,
    target_url: str | None,
    fields: list[str],
    output: str | None,
    requirements: list[str],
    parameters: dict[str, object] | None = None,
) -> list[str]:
    if task_type is not TaskType.SCRAPING:
        return []
    plan = [
        f"Открыть сайт {target_url}" if target_url else "Определить целевой сайт",
        "Изучить HTML и найти повторяющиеся карточки",
    ]
    if fields:
        plan.append(f"Извлечь поля: {', '.join(fields)}")
    else:
        plan.append("Уточнить список полей для извлечения")
    plan.append("Проверить пагинацию")
    if parameters:
        if parameters.get("scope") == "all_pages":
            plan.append("Режим: собрать все страницы")
        if parameters.get("pagination"):
            plan.append("Включить обход пагинации")
    if requirements:
        plan.append(f"Учесть требования: {', '.join(requirements)}")
    if output:
        plan.append(f"Экспортировать результат в {output.upper()}")
    return plan


def _mentions_card(text: str) -> bool:
    return bool(re.search(r"\b(карточ\w*|ozon[\s_-]*card|озон[\s_-]*карт)\b", text or ""))


def _mentions_batch(text: str) -> bool:
    return bool(re.search(r"\b(пачк\w*|пакет\w*|массов\w*|batch|несколько|карточки|карточек|список)\b", text or ""))


def _mentions_analytics(text: str) -> bool:
    return bool(re.search(r"\b(проанализируй|анализ|конкурент\w*|выдач\w*|рынок|аналитик)\b", text or ""))


def _is_update(text: str) -> bool:
    return bool(
        re.search(r"\b(обнови|обновить|проверь|проверить|перепроверь)\b", text)
        and re.search(r"\b(цен|цены|товар|товары|прайс)\b", text)
    )


def _extract_after_patterns(raw: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I | re.S)
        if match:
            payload = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:-")
            if payload:
                return payload
    return None


def _extract_card_payload(raw: str) -> str | None:
    payload = _extract_after_patterns(
        raw,
        [
            r"(?:сделай|составь|собери|создай|заполни|подготовь|сгенерируй|оформи)\s+(?:мне\s+)?(?:карточк[ауи]?|ozon[\s_-]*card|озон[\s_-]*карт\w*)(?:\s+(?:для|по|на|товара))?\s+(.+)$",
            r"(?:карточк[ауи]?|ozon[\s_-]*card|озон[\s_-]*карт\w*)\s+(?:для|по|на|товар)\s+(.+)$",
        ],
    )
    return payload


def _extract_search_query(raw: str) -> str | None:
    if _is_training_protocol_fragment(raw):
        return None
    payload = _extract_after_patterns(
        raw,
        [
            r"^(?:найди|найти|поищи|поиск|ищи)\s+(.+)$",
            r"^(?:цена на|сколько стоит|сколько стоит\s+на озоне)\s+(.+)$",
            r"^(?:спарси|парсани|пробей)\s+(.+)$",
        ],
    )
    if payload and not _is_training_protocol_fragment(payload):
        return payload
    low = raw.lower()
    if (
        not extract_urls(raw)
        and len(raw) >= 4
        and not re.search(r"^(привет|здорово|ок|спасибо|help|помощь)$", low)
        and not _is_training_protocol_fragment(raw)
    ):
        return raw
    return None


def _is_training_protocol_fragment(raw: str) -> bool:
    text = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", (raw or "").strip().lower())
    text = text.strip("`'\" :;,.")
    if not text:
        return False
    if text in {
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
    if re.search(r"[а-яё]", text, flags=re.I):
        return False
    tokens = set(re.findall(r"[a-z_]+", text))
    return bool(tokens) and tokens.issubset(protocol_tokens)
