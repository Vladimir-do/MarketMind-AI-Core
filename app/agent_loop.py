from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from app.task_intents import StructuredTask, TaskType


DEFAULT_MIN_CONFIDENCE = 0.85


class AgentLoopStage(StrEnum):
    CLASSIFY_PAGE = "classify_page"
    CHOOSE_STRATEGY = "choose_strategy"
    EXECUTE = "execute"
    EVALUATE_CONFIDENCE = "evaluate_confidence"
    FALLBACK_ON_ERROR = "fallback_on_error"
    SAVE_EXPERIENCE = "save_experience"
    REUSE_EXPERIENCE = "reuse_experience"
    REPRODUCE_FAILURE = "reproduce_failure"
    DIAGNOSE_FAILURE = "diagnose_failure"
    ASSESS_RISK = "assess_risk"
    CHECK_SAFETY_GATES = "check_safety_gates"
    WRITE_REGRESSION = "write_regression"
    IMPLEMENT_FIX = "implement_fix"
    VERIFY_FIX = "verify_fix"


@dataclass(frozen=True, slots=True)
class AgentLoopStep:
    stage: AgentLoopStage
    action: str
    uses_experience: bool = False
    records_experience: bool = False
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class AgentLoopPlan:
    task: StructuredTask
    steps: tuple[AgentLoopStep, ...]
    strategy: str
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    experience_key: str | None = None

    @property
    def stage_order(self) -> tuple[AgentLoopStage, ...]:
        return tuple(step.stage for step in self.steps)

    @property
    def classification_only(self) -> bool:
        return self.strategy == "classification_only"


def build_agent_loop(
    task: StructuredTask,
    *,
    has_experience: bool = False,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> AgentLoopPlan:
    """Build the reusable classify/execute/learn loop for an agent task."""

    experience_key = build_experience_key(task)

    if task.type is TaskType.PAGE_CLASSIFICATION_TRAINING:
        return AgentLoopPlan(
            task=task,
            strategy="classification_only",
            min_confidence=min_confidence,
            experience_key=experience_key,
            steps=(
                AgentLoopStep(
                    AgentLoopStage.CLASSIFY_PAGE,
                    "classify_page_before_parsing",
                ),
                AgentLoopStep(
                    AgentLoopStage.EVALUATE_CONFIDENCE,
                    "evaluate_page_structure_confidence",
                ),
                AgentLoopStep(
                    AgentLoopStage.SAVE_EXPERIENCE,
                    "save_classification_lesson",
                    records_experience=True,
                ),
            ),
        )

    if task.type is TaskType.REPAIR:
        return AgentLoopPlan(
            task=task,
            strategy="regression_first_repair",
            min_confidence=min_confidence,
            experience_key=experience_key,
            steps=(
                AgentLoopStep(AgentLoopStage.REPRODUCE_FAILURE, "reproduce_failure_or_capture_signal"),
                AgentLoopStep(
                    AgentLoopStage.DIAGNOSE_FAILURE,
                    "classify_failure_area",
                    uses_experience=has_experience,
                ),
                AgentLoopStep(
                    AgentLoopStage.ASSESS_RISK,
                    "assess_severity_blast_radius_and_evidence",
                ),
                AgentLoopStep(
                    AgentLoopStage.CHECK_SAFETY_GATES,
                    "check_repair_safety_gates_before_editing",
                ),
                AgentLoopStep(AgentLoopStage.WRITE_REGRESSION, "write_regression_test_for_failure"),
                AgentLoopStep(AgentLoopStage.IMPLEMENT_FIX, "implement_minimal_repair"),
                AgentLoopStep(AgentLoopStage.VERIFY_FIX, "run_focused_then_full_checks"),
                AgentLoopStep(
                    AgentLoopStage.SAVE_EXPERIENCE,
                    "save_repair_lesson",
                    records_experience=True,
                ),
            ),
        )

    strategy = strategy_for_task(task)
    steps: list[AgentLoopStep] = [
        AgentLoopStep(
            AgentLoopStage.CLASSIFY_PAGE,
            "detect_page_structure_before_parsing",
        )
    ]
    if has_experience:
        steps.append(
            AgentLoopStep(
                AgentLoopStage.REUSE_EXPERIENCE,
                "load_previous_strategy_signal",
                uses_experience=True,
            )
        )
    steps.extend(
        [
            AgentLoopStep(
                AgentLoopStage.CHOOSE_STRATEGY,
                strategy,
                uses_experience=has_experience,
            ),
            AgentLoopStep(
                AgentLoopStage.EXECUTE,
                executor_action_for(task),
            ),
            AgentLoopStep(
                AgentLoopStage.EVALUATE_CONFIDENCE,
                "evaluate_result_confidence",
            ),
            AgentLoopStep(
                AgentLoopStage.FALLBACK_ON_ERROR,
                "fallback_if_error_or_low_confidence",
                fallback=fallback_for_strategy(strategy),
            ),
            AgentLoopStep(
                AgentLoopStage.SAVE_EXPERIENCE,
                "save_execution_experience",
                records_experience=True,
            ),
        ]
    )

    return AgentLoopPlan(
        task=task,
        steps=tuple(steps),
        strategy=strategy,
        min_confidence=min_confidence,
        experience_key=experience_key,
    )


def should_fallback(
    *,
    confidence: float | None = None,
    error: BaseException | str | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> bool:
    if error is not None:
        return True
    if confidence is None:
        return False
    return confidence < min_confidence


def build_experience_key(task: StructuredTask) -> str | None:
    target = task.target_url or (task.target_urls[0] if task.target_urls else None)
    if target:
        parsed = urlparse(target)
        host = (parsed.netloc or "").lower()
        path = parsed.path.rstrip("/") or "/"
        return f"{task.type.value}:{host}{path}"
    if task.query:
        return f"{task.type.value}:query:{task.query.strip().lower()}"
    if isinstance(task.payload, str) and task.payload.strip():
        return f"{task.type.value}:payload:{task.payload.strip().lower()}"
    return task.type.value


def strategy_for_task(task: StructuredTask) -> str:
    if task.type is TaskType.SCRAPING:
        if task.parameters.get("pagination") or task.parameters.get("scope") == "all_pages":
            return "catalog_paginated_scraping"
        return "classify_then_scrape"
    if task.type is TaskType.MARKETPLACE_SEARCH:
        return "marketplace_search"
    if task.type is TaskType.ADD_URLS:
        return "marketplace_url_monitoring"
    if task.type is TaskType.REPAIR:
        return "regression_first_repair"
    return "intent_plan_execution"


def executor_action_for(task: StructuredTask) -> str:
    if task.type is TaskType.SCRAPING:
        return "run_scraping_pipeline"
    if task.type is TaskType.MARKETPLACE_SEARCH:
        return "run_marketplace_search"
    if task.type is TaskType.CARD_GENERATION:
        return "generate_marketplace_card"
    if task.type is TaskType.ADD_URLS:
        return "add_marketplace_urls"
    if task.type is TaskType.REPAIR:
        return "run_self_healing_repair_loop"
    return "run_planned_executor"


def fallback_for_strategy(strategy: str) -> str:
    if strategy == "catalog_paginated_scraping":
        return "retry_first_page_then_detail_fallback"
    if strategy == "classify_then_scrape":
        return "retry_with_browser_or_structured_source"
    if strategy == "marketplace_search":
        return "ask_for_more_specific_product_query"
    if strategy == "marketplace_url_monitoring":
        return "retry_with_marketplace_router"
    if strategy == "regression_first_repair":
        return "capture_failure_signal_and_request_missing_repro"
    return "return_clarifying_question_or_missing_executor"


def stage_label_ru(stage: AgentLoopStage) -> str:
    repair_labels = {
        AgentLoopStage.REPRODUCE_FAILURE: "reproduce failure",
        AgentLoopStage.DIAGNOSE_FAILURE: "diagnose failure",
        AgentLoopStage.ASSESS_RISK: "assess risk",
        AgentLoopStage.CHECK_SAFETY_GATES: "check safety gates",
        AgentLoopStage.WRITE_REGRESSION: "write regression",
        AgentLoopStage.IMPLEMENT_FIX: "implement fix",
        AgentLoopStage.VERIFY_FIX: "verify fix",
    }
    if stage in repair_labels:
        return repair_labels[stage]
    labels = {
        AgentLoopStage.CLASSIFY_PAGE: "определить тип страницы",
        AgentLoopStage.CHOOSE_STRATEGY: "выбрать стратегию",
        AgentLoopStage.EXECUTE: "выполнить",
        AgentLoopStage.EVALUATE_CONFIDENCE: "оценить confidence",
        AgentLoopStage.FALLBACK_ON_ERROR: "fallback при ошибке",
        AgentLoopStage.SAVE_EXPERIENCE: "сохранить опыт",
        AgentLoopStage.REUSE_EXPERIENCE: "использовать опыт",
    }
    return labels[stage]
