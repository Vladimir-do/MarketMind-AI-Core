from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.skill_manifest import ScoringPolicy, SkillGraph, SkillManifest, SkillQuality, load_default_skill_graph
from app.task_intents import StructuredTask, TaskType


class SkillStatus(StrEnum):
    AVAILABLE = "available"
    PLANNED = "planned"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class SkillSpec:
    skill_id: str
    title: str
    status: SkillStatus
    handles: tuple[TaskType, ...] = ()
    outputs: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    category: str = "general"
    quality: SkillQuality = field(default_factory=SkillQuality)
    scoring_policy: ScoringPolicy = ScoringPolicy.BALANCED
    selected_for: str | None = None


@dataclass(frozen=True, slots=True)
class PlanStep:
    index: int
    skill_id: str
    title: str
    status: SkillStatus
    action: str
    category: str = "general"
    quality_score: float = 0.0
    selected_for: str | None = None


@dataclass(frozen=True, slots=True)
class TaskPlan:
    task: StructuredTask
    steps: list[PlanStep]
    self_critic: list[str] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        return all(step.status is SkillStatus.AVAILABLE for step in self.steps)

    @property
    def missing_skills(self) -> list[str]:
        return [step.skill_id for step in self.steps if step.status is not SkillStatus.AVAILABLE]


class SkillRegistry:
    def __init__(
        self,
        skills: list[SkillSpec] | None = None,
        graph: SkillGraph | None = None,
        scoring_policy: ScoringPolicy | str = ScoringPolicy.BALANCED,
    ):
        self.scoring_policy = ScoringPolicy(scoring_policy)
        self.graph = graph if graph is not None else load_default_skill_graph(scoring_policy=self.scoring_policy)
        self._skills = _skills_from_graph(self.graph, self.scoring_policy)
        for skill in (skills or []):
            self._skills.setdefault(skill.skill_id, skill)

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._skills[skill_id]
        except KeyError:
            return SkillSpec(skill_id, skill_id, SkillStatus.MISSING)

    def choose_for_task(self, task: StructuredTask) -> list[SkillSpec]:
        if task.type is TaskType.SCRAPING:
            skill_ids = [
                "scraping.manual_plan",
                "scraping.fetch_pages",
            ]
            if task.parameters.get("scope") == "all_pages" or task.parameters.get("pagination"):
                skill_ids.append("pagination.detect")
            skill_ids.extend([
                "scraping.extract_products",
                "scraping.validate_result",
            ])
            if task.output:
                skill_ids.append(f"{task.output}.export")
            skill_ids.append("quality.self_critic")
            return [self.get(skill_id) for skill_id in skill_ids]

        if task.type is TaskType.MARKETPLACE_SEARCH:
            return self.resolve(["market.search"])
        if task.type is TaskType.CARD_GENERATION:
            return self.resolve(["ozon.card.generate"])
        if task.type is TaskType.BATCH:
            return self.resolve(["batch.cards"])
        if task.type is TaskType.UPDATE:
            return self.resolve(["market.update"])
        if task.type is TaskType.ANALYTICS:
            return self.resolve(["market.analytics"])
        if task.type is TaskType.PAGE_CLASSIFICATION_TRAINING:
            return [self.get("page.classification.training")]
        if task.type is TaskType.REPAIR:
            return [
                self.get("repair.reproduce"),
                self.get("repair.classify"),
                self.get("repair.regression_test"),
                self.get("repair.implement_fix"),
                self.get("repair.verify"),
                self.get("repair.skillpack_update"),
                self.get("quality.self_critic"),
            ]
        return self.resolve(["intent.unknown"])

    def resolve(self, skill_ids: list[str]) -> list[SkillSpec]:
        resolution = self.graph.resolve(skill_ids)
        if not resolution.steps:
            return [self.get(skill_id) for skill_id in skill_ids]
        return _move_self_critic_last([
            _spec_from_manifest(step.manifest, selected_for=step.selected_for, scoring_policy=self.scoring_policy)
            for step in resolution.steps
        ])


class TaskPlanner:
    def __init__(
        self,
        registry: SkillRegistry | None = None,
        scoring_policy: ScoringPolicy | str = ScoringPolicy.BALANCED,
    ):
        self.registry = registry or SkillRegistry(scoring_policy=scoring_policy)

    def build_plan(self, task: StructuredTask) -> TaskPlan:
        skills = self.registry.choose_for_task(task)
        steps = [
            PlanStep(
                index=index,
                skill_id=skill.skill_id,
                title=skill.title,
                status=skill.status,
                action=_action_for(skill, task),
                category=skill.category,
                quality_score=skill.quality.score_for(skill.scoring_policy),
                selected_for=skill.selected_for,
            )
            for index, skill in enumerate(skills, 1)
        ]
        return TaskPlan(task=task, steps=steps, self_critic=_self_critic_for(task))


def default_skills() -> list[SkillSpec]:
    """Возвращает список всех базовых SkillSpec для инициализации реестра."""
    return [
        # ── Scraping ─────────────────────────────────────────────────────────
        SkillSpec(
            skill_id="scraping.manual_plan",
            title="Manual Scraping Plan",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.SCRAPING,),
            outputs=("execution_plan",),
            requirements=("quality.self_critic",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="scraping.fetch_pages",
            title="Fetch Scraping Pages",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.SCRAPING,),
            outputs=("html_pages",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="scraping.extract_products",
            title="Extract Product Records",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.SCRAPING,),
            outputs=("product_records",),
            requirements=("scraping.fetch_pages",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="scraping.validate_result",
            title="Validate Scraped Result",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.SCRAPING,),
            outputs=("validation_report",),
            requirements=("scraping.extract_products",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="scraping.generic",
            title="Generic Website Scraper",
            status=SkillStatus.MISSING,
            handles=(TaskType.SCRAPING,),
            outputs=("scraped_records",),
            requirements=("html.fetch", "html.parse"),
            category="scraping",
        ),
        SkillSpec(
            skill_id="scraping.website",
            title="Generic Website Scraping Pipeline",
            status=SkillStatus.MISSING,
            handles=(TaskType.SCRAPING,),
            outputs=("scraped_records",),
            requirements=("html.fetch", "html.parse", "pagination.detect"),
            category="scraping",
        ),
        # ── Core scraping helpers ────────────────────────────────────────────
        SkillSpec(
            skill_id="html.fetch",
            title="HTML Fetch",
            status=SkillStatus.MISSING,
            outputs=("html",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="html.parse",
            title="HTML Parse",
            status=SkillStatus.MISSING,
            outputs=("records",),
            requirements=("html.fetch",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="browser.fetch",
            title="Browser Fetch Fallback",
            status=SkillStatus.PLANNED,
            outputs=("rendered_html",),
            category="scraping",
        ),
        SkillSpec(
            skill_id="pagination.detect",
            title="Pagination Detector",
            status=SkillStatus.AVAILABLE,
            outputs=("pagination_strategy",),
            requirements=("html.fetch",),
            category="scraping",
        ),
        # ── Marketplace ──────────────────────────────────────────────────────
        SkillSpec(
            skill_id="market.search",
            title="Ozon Marketplace Search",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.MARKETPLACE_SEARCH, TaskType.ANALYTICS),
            outputs=("search_results",),
            category="marketplace",
        ),
        SkillSpec(
            skill_id="market.update",
            title="Tracked Products Update Worker",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.UPDATE,),
            outputs=("price_history",),
            category="marketplace",
        ),
        SkillSpec(
            skill_id="market.analytics",
            title="Marketplace Competitor Analytics",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.ANALYTICS,),
            outputs=("competitor_report",),
            requirements=("market.search", "quality.self_critic"),
            category="marketplace",
        ),
        # ── Card Generation ──────────────────────────────────────────────────
        SkillSpec(
            skill_id="ozon.card.generate",
            title="Ozon Card Draft Generator",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.CARD_GENERATION,),
            outputs=("ozon_card_draft",),
            requirements=("quality.self_critic",),
            category="card_generation",
        ),
        SkillSpec(
            skill_id="batch.cards",
            title="Batch Ozon Card Files",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.BATCH,),
            outputs=("batch_card_files",),
            requirements=("ozon.card.generate", "xlsx.export", "json.export"),
            category="batch",
        ),
        # ── Export ───────────────────────────────────────────────────────────
        SkillSpec(
            skill_id="csv.export",
            title="CSV Export",
            status=SkillStatus.AVAILABLE,
            outputs=("csv",),
            category="export",
        ),
        SkillSpec(
            skill_id="xlsx.export",
            title="XLSX Export",
            status=SkillStatus.AVAILABLE,
            outputs=("xlsx",),
            category="export",
        ),
        SkillSpec(
            skill_id="json.export",
            title="JSON Export",
            status=SkillStatus.AVAILABLE,
            outputs=("json",),
            category="export",
        ),
        SkillSpec(
            skill_id="html.export",
            title="HTML Export",
            status=SkillStatus.PLANNED,
            outputs=("html",),
            category="export",
        ),
        # ── Quality ──────────────────────────────────────────────────────────
        SkillSpec(
            skill_id="quality.self_critic",
            title="Self-Critic Checklist",
            status=SkillStatus.AVAILABLE,
            handles=(
                TaskType.SCRAPING,
                TaskType.CARD_GENERATION,
                TaskType.BATCH,
                TaskType.MARKETPLACE_SEARCH,
                TaskType.UPDATE,
                TaskType.ANALYTICS,
                TaskType.REPAIR,
            ),
            outputs=("validation_checklist",),
            category="quality",
        ),
        # ── Training ─────────────────────────────────────────────────────────
        SkillSpec(
            skill_id="page.classification.training",
            title="Page Classification Training",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.PAGE_CLASSIFICATION_TRAINING,),
            outputs=("page_classification",),
            category="training",
        ),
        # ── Repair ───────────────────────────────────────────────────────────
        SkillSpec(
            skill_id="repair.reproduce",
            title="Repair Failure Reproduction",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("failure_signal",),
            category="repair",
        ),
        SkillSpec(
            skill_id="repair.classify",
            title="Repair Failure Classification",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("failure_area", "severity", "evidence_types", "blast_radius", "safety_gates", "verification_scope"),
            requirements=("repair.reproduce",),
            category="repair",
        ),
        SkillSpec(
            skill_id="repair.regression_test",
            title="Repair Regression Test",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("regression_test",),
            requirements=("repair.classify",),
            category="repair",
        ),
        SkillSpec(
            skill_id="repair.implement_fix",
            title="Repair Implementation",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("code_fix",),
            requirements=("repair.regression_test",),
            category="repair",
        ),
        SkillSpec(
            skill_id="repair.verify",
            title="Repair Verification",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("verification_signal", "focused_tests", "full_suite_decision", "smoke_check_decision"),
            requirements=("repair.implement_fix",),
            category="repair",
        ),
        SkillSpec(
            skill_id="repair.skillpack_update",
            title="Repair Skillpack Feedback",
            status=SkillStatus.AVAILABLE,
            handles=(TaskType.REPAIR,),
            outputs=("reusable_lesson",),
            requirements=("repair.verify",),
            category="repair",
        ),
        # ── Intent Fallback ──────────────────────────────────────────────────
        SkillSpec(
            skill_id="intent.unknown",
            title="Unknown Intent Fallback",
            status=SkillStatus.MISSING,
            handles=(TaskType.UNKNOWN,),
            category="intent",
        ),
    ]


def _skills_from_graph(graph: SkillGraph, scoring_policy: ScoringPolicy | str) -> dict[str, SkillSpec]:
    return {
        manifest.skill_id: _spec_from_manifest(manifest, scoring_policy=scoring_policy)
        for manifest in graph.manifests
    }


def _spec_from_manifest(
    manifest: SkillManifest,
    selected_for: str | None = None,
    scoring_policy: ScoringPolicy | str = ScoringPolicy.BALANCED,
) -> SkillSpec:
    return SkillSpec(
        skill_id=manifest.skill_id,
        title=manifest.name,
        status=_status_from_manifest(manifest.status),
        outputs=manifest.provides,
        requirements=manifest.requires,
        category=manifest.category,
        quality=manifest.quality,
        scoring_policy=ScoringPolicy(scoring_policy),
        selected_for=selected_for,
    )


def _status_from_manifest(status: str) -> SkillStatus:
    try:
        return SkillStatus(status)
    except ValueError:
        return SkillStatus.MISSING


def _move_self_critic_last(skills: list[SkillSpec]) -> list[SkillSpec]:
    regular = [skill for skill in skills if skill.skill_id != "quality.self_critic"]
    critics = [skill for skill in skills if skill.skill_id == "quality.self_critic"]
    return regular + critics


def _action_for(skill: SkillSpec, task: StructuredTask) -> str:
    if skill.skill_id in {"scraping.generic", "scraping.website", "scraping.manual_plan"}:
        target = task.target_url or "целевой сайт"
        fields = ", ".join(task.fields) if task.fields else "поля из ТЗ"
        if skill.skill_id == "scraping.manual_plan":
            return f"Собрать исполнимый план парсинга для {target}: {fields}"
        return f"Собрать данные с {target}: {fields}"
    if skill.skill_id == "scraping.fetch_pages":
        if task.parameters.get("scope") == "all_pages":
            return "Получить все страницы каталога с учетом пагинации"
        return "Получить целевые страницы для парсинга"
    if skill.skill_id == "scraping.extract_products":
        fields = ", ".join(task.fields) if task.fields else "поля из ТЗ"
        return f"Извлечь товары и поля: {fields}"
    if skill.skill_id == "scraping.validate_result":
        return "Проверить полноту, дубли, пустые значения и соответствие схеме"
    if skill.skill_id == "html.fetch":
        return "Получить HTML целевой страницы"
    if skill.skill_id == "browser.fetch":
        return "Получить rendered HTML через browser fallback"
    if skill.skill_id == "html.parse":
        return "Разобрать HTML и извлечь записи"
    if skill.skill_id == "pagination.detect":
        return "Проверить пагинацию и переходы между страницами"
    if skill.skill_id.endswith(".export"):
        output = skill.skill_id.split(".", 1)[0].upper()
        return f"Экспортировать результат в {output}"
    if skill.skill_id == "quality.self_critic":
        return "Проверить полноту, ошибки, retry/delay и формат результата"
    if skill.skill_id == "page.classification.training":
        return "Классифицировать страницу перед парсингом и запросить URL, если его нет"
    if skill.skill_id == "repair.reproduce":
        return "Reproduce the failure or capture a measurable failure signal"
    if skill.skill_id == "repair.classify":
        return f"Classify failure area: {task.parameters.get('failure_area', 'unknown')}"
    if skill.skill_id == "repair.regression_test":
        return "Add a regression test that protects the fix"
    if skill.skill_id == "repair.implement_fix":
        return "Implement the smallest fix at the failing layer"
    if skill.skill_id == "repair.verify":
        return "Run focused tests and full/smoke checks when the blast radius is shared"
    if skill.skill_id == "repair.skillpack_update":
        return "Save the reusable repair lesson in the skillpack and validate it"
    if skill.skill_id == "market.search":
        return f"Найти товары по запросу: {task.query or task.payload}"
    if skill.skill_id == "ozon.card.generate":
        return "Собрать черновик карточки Ozon"
    if skill.skill_id == "batch.cards":
        return "Обработать список карточек пакетно"
    if skill.skill_id == "market.update":
        return "Обновить отслеживаемые товары"
    if skill.skill_id == "market.analytics":
        return f"Проанализировать конкурентов: {task.query or task.payload}"
    return "Уточнить задачу"


def _self_critic_for(task: StructuredTask) -> list[str]:
    checks = ["Intent выбран корректно", "План не запускает отсутствующий executor молча"]
    if task.type is TaskType.SCRAPING:
        checks.extend(
            [
                "Целевой URL определён",
                "Поля отделены от требований",
                "Проверена пагинация",
                "Учтены logging/retry/delay/error handling",
            ]
        )
        if task.output:
            checks.append(f"Формат вывода {task.output.upper()} указан явно")
    elif task.type in {TaskType.CARD_GENERATION, TaskType.BATCH}:
        checks.extend(["Обязательные поля карточки заполнены", "Экспортные файлы сформированы"])
    elif task.type is TaskType.MARKETPLACE_SEARCH:
        checks.append("Запрос не является URL товара")
    elif task.type is TaskType.REPAIR:
        checks.extend(
            [
                "Severity, evidence types, blast radius and safety gates are explicit",
                "Failure signal is reproducible or captured",
                "Regression test protects the repaired behavior",
                "Verification scope matches focused/full/live-smoke risk",
                "Reusable lesson was saved to skillpack or session updates",
            ]
        )
    return checks
