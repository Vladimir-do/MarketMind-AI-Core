from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ExecutionStatus(StrEnum):
    PLANNING = "planning"
    PREPARING = "preparing"
    EXECUTING = "executing"
    VALIDATING = "validating"
    RECOVERING = "recovering"
    FINISHED = "finished"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.PLANNING: {ExecutionStatus.PREPARING, ExecutionStatus.FAILED},
    ExecutionStatus.PREPARING: {ExecutionStatus.EXECUTING, ExecutionStatus.RECOVERING, ExecutionStatus.FAILED},
    ExecutionStatus.EXECUTING: {ExecutionStatus.VALIDATING, ExecutionStatus.RECOVERING, ExecutionStatus.FAILED},
    ExecutionStatus.VALIDATING: {ExecutionStatus.FINISHED, ExecutionStatus.RECOVERING, ExecutionStatus.FAILED},
    ExecutionStatus.RECOVERING: {ExecutionStatus.PREPARING, ExecutionStatus.EXECUTING, ExecutionStatus.FAILED},
    ExecutionStatus.FINISHED: set(),
    ExecutionStatus.FAILED: set(),
}


@dataclass(slots=True)
class ExecutionStep:
    skill_id: str
    status: ExecutionStatus = ExecutionStatus.PLANNING
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class ExecutionRun:
    run_id: str
    skill_ids: list[str]
    status: ExecutionStatus = ExecutionStatus.PLANNING
    current_index: int = 0
    steps: list[ExecutionStep] = field(default_factory=list)
    history: list[ExecutionStatus] = field(default_factory=lambda: [ExecutionStatus.PLANNING])

    def __post_init__(self) -> None:
        if not self.steps:
            self.steps = [ExecutionStep(skill_id) for skill_id in self.skill_ids]

    @property
    def current_step(self) -> ExecutionStep | None:
        if self.current_index >= len(self.steps):
            return None
        return self.steps[self.current_index]

    def transition(self, next_status: ExecutionStatus) -> None:
        allowed = ALLOWED_TRANSITIONS[self.status]
        if next_status not in allowed:
            raise ValueError(f"Invalid transition: {self.status.value} -> {next_status.value}")
        self.status = next_status
        self.history.append(next_status)

    def start_current_step(self) -> None:
        step = self.current_step
        if step is None:
            raise ValueError("No current execution step")
        step.status = ExecutionStatus.EXECUTING
        step.started_at = datetime.now(timezone.utc)
        if self.status is not ExecutionStatus.EXECUTING:
            self.transition(ExecutionStatus.EXECUTING)

    def finish_current_step(self) -> None:
        step = self.current_step
        if step is None:
            raise ValueError("No current execution step")
        step.status = ExecutionStatus.FINISHED
        step.finished_at = datetime.now(timezone.utc)
        self.current_index += 1
        if self.current_index >= len(self.steps):
            if self.status is not ExecutionStatus.VALIDATING:
                self.transition(ExecutionStatus.VALIDATING)
            self.transition(ExecutionStatus.FINISHED)

    def fail_current_step(self, error: str, recoverable: bool = True) -> None:
        step = self.current_step
        if step is None:
            raise ValueError("No current execution step")
        step.error = error
        step.finished_at = datetime.now(timezone.utc)
        next_status = ExecutionStatus.RECOVERING if recoverable else ExecutionStatus.FAILED
        step.status = next_status
        self.transition(next_status)
